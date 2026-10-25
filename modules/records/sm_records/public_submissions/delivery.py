"""One delivery attempt of a submission's notification, recipient by recipient.

SMTP cannot be made exactly-once, but a retry must not mail a recipient whose
send went through, and two outbox workers running one attempt must not both
send. So every recipient of an attempt is **claimed** first, in the internal
``records_submission_delivery`` table, whose unique key
``(tenant, record, attempt, recipient)`` makes the claim the database's
decision — an ``INSERT``, or for a row a crashed worker left behind, a
conditional ``UPDATE`` that takes over a claim older than :data:`LEASE`. A
claim, a release and a "sent" each commit in a session of their own, so a
rollback of the caller's transaction (the outbox's ``ctx.db``, or the
after-commit task's session) never loses them.

* A row with ``sent_at`` is never sent again.
* A send that raises releases its claim (``claimed_at = NULL``) so the retry
  takes it at once; a crash leaves it to expire.
* A recipient claimed by another worker, still inside its lease, raises
  :class:`DeliveryInProgress`: the outbox retries later, and the record is not
  marked notified until every recipient is sent.

The attempt is ``NotificationDue.attempt``, minted when the notification is
queued, so an explicit *Resend* is a new attempt that reaches everyone again.
An event queued without one gets a stable id derived from its own payload
(:func:`attempt_of`) — the outbox's ``DurableContext`` does not expose the
event's row id.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any, Final, Literal

from simple_module_core.mail import MailSender
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.models import Record, RecordType, SubmissionDelivery
from sm_records.public_submissions.mail import notification
from sm_records.public_submissions.system import system_update
from sm_records.services._common import utcnow
from sm_records.services.errors import NotFound
from sm_records.services.records import get_record
from sm_records.services.types import get_type
from sm_records.settings import RecordsSettings

__all__ = ["LEASE", "DeliveryInProgress", "attempt_of", "claim", "deliver", "load"]

logger = logging.getLogger(__name__)

LEASE: Final = timedelta(minutes=10)
"""How long a claim that was never marked sent blocks everyone else. Far
longer than one SMTP send; short enough that a crashed worker's recipient is
retried the same hour."""

SessionFactory = Callable[[], AsyncSession]
Claim = Literal["claimed", "sent", "busy"]


class DeliveryInProgress(RuntimeError):  # noqa: N818 - reads as the condition it is
    """Another worker holds a live claim on a recipient of this attempt."""


def attempt_of(due: Any) -> str:
    if due.attempt:
        return str(due.attempt)
    raw = "|".join((due.tenant_id, due.type_key, due.uuid, due.base_url, due.locale))
    return "legacy-" + hashlib.sha256(raw.encode()).hexdigest()[:32]


async def load(db: AsyncSession, due: Any) -> tuple[RecordType, Record] | None:
    """The type and the live record, or ``None`` when either has gone — a
    record trashed or purged before its mail went out is not mailed."""
    try:
        rtype = await get_type(db, due.type_key)
        return rtype, await get_record(db, rtype, due.uuid)
    except NotFound:
        logger.info("records: %s submission %s is gone; not mailed", due.type_key, due.uuid)
        return None


def _key(tenant: str, uuid: str, attempt: str, recipient: str) -> tuple[Any, ...]:
    table = SubmissionDelivery
    return (
        table.tenant_id == tenant,
        table.record_uuid == uuid,
        table.attempt == attempt,
        table.recipient == recipient,
    )


async def _apply(factory: SessionFactory, stmt: Any) -> int:
    session = factory()
    try:
        result = await session.execute(stmt)
        await events.commit(session)
        return int(result.rowcount or 0)
    finally:
        await session.close()


async def claim(
    factory: SessionFactory, tenant: str, uuid: str, attempt: str, recipient: str
) -> Claim:
    """Take ``recipient`` for this attempt, or say why not."""
    now = utcnow()
    session = factory()
    try:
        session.add(
            SubmissionDelivery(
                tenant_id=tenant,
                record_uuid=uuid,
                attempt=attempt,
                recipient=recipient,
                claimed_at=now,
            )
        )
        try:
            await events.commit(session)
            return "claimed"
        except IntegrityError:
            await events.rollback(session)
        table = SubmissionDelivery
        key = _key(tenant, uuid, attempt, recipient)
        expired = or_(table.claimed_at.is_(None), table.claimed_at < now - LEASE)
        stmt = update(table).where(*key, table.sent_at.is_(None), expired).values(claimed_at=now)
        result = await session.execute(stmt)
        await events.commit(session)
        if result.rowcount == 1:
            return "claimed"
        sent = await session.execute(select(table.sent_at).where(*key))
        return "sent" if sent.scalar_one_or_none() is not None else "busy"
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
    """Mail every recipient this attempt has not reached, then mark the record
    notified. A failed send raises; the recipients before it stay sent."""
    tenant, attempt, busy = rtype.tenant_id, attempt_of(due), False
    for to in (rtype.public_submissions or {}).get("notify_to", []):
        state = await claim(factory, tenant, record.uuid, attempt, to)
        if state != "claimed":
            busy = busy or state == "busy"
            continue
        key = _key(tenant, record.uuid, attempt, to)
        try:
            message = notification(rtype, record, to=to, base_url=due.base_url, locale=due.locale)
            await sender.send(message)
        except BaseException:
            release = update(SubmissionDelivery).where(*key, SubmissionDelivery.sent_at.is_(None))
            await _apply(factory, release.values(claimed_at=None))
            raise
        await _apply(factory, update(SubmissionDelivery).where(*key).values(sent_at=utcnow()))
    if busy:
        raise DeliveryInProgress(f"another worker is still mailing submission {record.uuid}")
    await system_update(db, rtype, record, {"sm_notified_at": utcnow()}, settings=settings)
