"""One delivery attempt of a submission's notification, recipient by recipient.

SMTP cannot be made exactly-once, but a retry must not mail a recipient whose
send already went through. Each attempt has an id (``NotificationDue.attempt``
— minted when the notification is queued, so an explicit *Resend* is a new
attempt that mails everyone again). After every successful send the
recipients this attempt has reached are written to the record's internal
``sm_delivery`` field **in a session of their own, committed at once** — the
caller's transaction (the outbox's ``ctx.db``, or the after-commit task's
session) is rolled back when a later recipient fails, and the retry has to
find the progress anyway. A retry of the same attempt skips everyone listed.
Once all are reached, ``sm_notified_at`` and the final ``sm_delivery`` are
written through the caller's session as before.

A type saved before ``sm_delivery`` existed has no such field until its next
save (``normalise`` injects it then); it is mailed without progress tracking.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Final

from simple_module_core.mail import MailSender
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.models import Record, RecordType
from sm_records.public_submissions.mail import notification
from sm_records.public_submissions.system import system_update
from sm_records.services._common import utcnow
from sm_records.services._payload import field_defs
from sm_records.services.errors import NotFound
from sm_records.services.records import get_record
from sm_records.services.types import get_type
from sm_records.settings import RecordsSettings

__all__ = ["PROGRESS_KEY", "deliver", "load", "sent_so_far"]

logger = logging.getLogger(__name__)

PROGRESS_KEY: Final = "sm_delivery"

SessionFactory = Callable[[], AsyncSession]


async def load(db: AsyncSession, due: Any) -> tuple[RecordType, Record] | None:
    """The type and the live record, or ``None`` when either has gone — a
    record trashed or purged before its mail went out is not mailed."""
    try:
        rtype = await get_type(db, due.type_key)
        return rtype, await get_record(db, rtype, due.uuid)
    except NotFound:
        logger.info("records: %s submission %s is gone; not mailed", due.type_key, due.uuid)
        return None


def _tracks(rtype: RecordType) -> bool:
    return any(entry.key == PROGRESS_KEY for entry in field_defs(rtype))


def _state(due: Any, sent: set[str]) -> str:
    return json.dumps({"attempt": due.attempt, "sent": sorted(sent)})


def sent_so_far(record: Record, due: Any) -> set[str]:
    """The recipients this attempt has already reached, per the record."""
    raw = (record.data or {}).get(PROGRESS_KEY)
    try:
        state = json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        return set()
    if not due.attempt or not isinstance(state, dict) or state.get("attempt") != due.attempt:
        return set()
    return {str(address) for address in state.get("sent") or []}


async def _save_progress(
    factory: SessionFactory, due: Any, sent: set[str], settings: RecordsSettings
) -> None:
    """Commit this attempt's progress on its own, whatever happens next."""
    session = factory()
    try:
        loaded = await load(session, due)
        if loaded is not None:
            await system_update(
                session, *loaded, {PROGRESS_KEY: _state(due, sent)}, settings=settings
            )
            await events.commit(session)
    except Exception:
        # The send went through; failing to record it costs at worst a repeat
        # to this one recipient on a retry, which is not worth an error here.
        logger.exception("records: recording delivery progress of %s failed", due.uuid)
        await events.rollback(session)
    finally:
        await session.close()


async def deliver(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    sender: MailSender,
    due: Any,
    settings: RecordsSettings,
    factory: SessionFactory,
) -> None:
    """Mail every recipient this attempt has not reached yet, then mark the
    record notified. A failed send raises after the earlier ones are recorded."""
    tracks = _tracks(rtype)
    sent = sent_so_far(record, due) if tracks else set()
    for to in (rtype.public_submissions or {}).get("notify_to", []):
        if to in sent:
            continue
        await sender.send(
            notification(rtype, record, to=to, base_url=due.base_url, locale=due.locale)
        )
        sent.add(to)
        if tracks:
            await _save_progress(factory, due, sent, settings)
    values: dict[str, Any] = {"sm_notified_at": utcnow()}
    if tracks:
        values[PROGRESS_KEY] = _state(due, sent)
    await system_update(db, rtype, record, values, settings=settings)
