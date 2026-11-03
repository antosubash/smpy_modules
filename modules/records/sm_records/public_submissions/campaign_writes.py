"""The writes behind the newsletter contract: unsubscribe and tags (PR 1).

No FastAPI, no commit: both run in the caller's transaction, through records'
own services, and the caller finishes it (``simple_module_db.finalize_session``
or records' ``events.commit``), after which ``SubscriptionChanged`` and
``RecordUpdated`` are published. The tenant is bound by the contract; every
lookup here names it again as a ``WHERE``.

**Unsubscribe** is :func:`.opt_in.leave` with a condition re-checked on the
row each attempt: a live, ``confirmed`` subscriber confirmed at or before the
cutoff, or one whose confirmation time is missing or unreadable (a re-signup
after the cutoff cannot be shown). A re-signup since the mail (``pending``
again, or confirmed later) is left alone. The answer is the transition's ``Outcome.wrote``.

**Tags** are an ordinary ``update_record`` at the version read, retried once
if the row moved in between; a value outside the field's choices is records'
``ValidationFailed``, unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.core.settings import RecordsSettings
from sm_records.models import Record, RecordType, tables_for
from sm_records.public_submissions import opt_in
from sm_records.public_submissions.campaign_reads import list_type, moment, stored_tags
from sm_records.public_submissions.subscribe import CONFIRMED
from sm_records.public_submissions.system import _ordinary, _reload
from sm_records.records.services import records as record_service
from sm_records.records.services.errors import Conflict

__all__ = ["TAGS", "SubscriberNotFound", "set_tags", "unsubscribe"]

TAGS = "tags"
"""The ordinary field a list's tags live in."""


class SubscriberNotFound(LookupError):  # noqa: N818 - the contract's name for it
    """No live subscriber of that uuid on that list, in that tenant."""


async def _record(db: AsyncSession, rtype: RecordType, tenant_id: str, uuid: str) -> Record | None:
    """The untrashed record (the framework's soft-delete filter applies)."""
    cls = tables_for(rtype).record
    stmt = select(cls).where(cls.tenant_id == tenant_id, cls.type_id == rtype.id, cls.uuid == uuid)
    return (await db.execute(stmt)).scalars().first()


def _holds(cutoff: datetime | None):
    def still(row: Record) -> bool:
        data = row.data or {}
        if row.is_deleted or data.get("sm_status") != CONFIRMED:
            return False
        if cutoff is None:
            return True
        confirmed_at = moment(data.get("sm_confirmed_at"))
        # No provable confirmation time: a re-signup after the cutoff cannot be
        # shown, and failing to honour an unsubscribe is the worse error.
        return confirmed_at is None or confirmed_at <= cutoff

    return still


async def unsubscribe(
    db: AsyncSession,
    tenant_id: str,
    type_key: str,
    uuid: str,
    cutoff: datetime | None,
    settings: RecordsSettings,
) -> bool:
    """Whether this call unsubscribed ``uuid``; ``False`` for an unknown,
    trashed, pending or unsubscribed one, or one confirmed after ``cutoff``."""
    rtype = await list_type(db, tenant_id, type_key)
    if rtype is None:
        return False
    record = await _record(db, rtype, tenant_id, uuid)
    if record is None:
        return False
    outcome = await opt_in.leave(db, rtype, record, settings, still=_holds(cutoff))
    return outcome.wrote


def _merged(stored: object, add: Sequence[str], remove: Sequence[str]) -> list[str]:
    """Stored order kept, new tags appended, duplicates dropped; removal wins."""
    current = stored_tags(stored)
    gone = set(remove)
    out: list[str] = []
    for tag in [*current, *add]:
        if tag not in gone and tag not in out:
            out.append(tag)
    return out


async def set_tags(
    db: AsyncSession,
    tenant_id: str,
    type_key: str,
    uuid: str,
    add: Sequence[str],
    remove: Sequence[str],
    settings: RecordsSettings,
) -> tuple[RecordType, Record]:
    """Add and remove tags on a live subscriber; the type and the written row.

    :class:`SubscriberNotFound` for an unknown or trashed one (or no such
    list in this tenant). A merged list equal to the stored one writes nothing."""
    rtype = await list_type(db, tenant_id, type_key)
    record = None if rtype is None else await _record(db, rtype, tenant_id, uuid)
    if rtype is None or record is None:
        raise SubscriberNotFound(f"no subscriber {uuid!r} on {type_key!r}")
    for attempt in range(2):
        stored = (record.data or {}).get(TAGS)
        tags = _merged(stored, add, remove)
        # No stored tags is the empty list: removing a tag from such a
        # subscriber changes nothing and must not write.
        if tags == ([] if stored is None else stored):
            return rtype, record  # nothing to change: no version bump, no event
        try:
            written = await record_service.update_record(
                db,
                rtype,
                record,
                expected_version=record.version,
                data={**_ordinary(rtype, record), TAGS: tags},
                settings=settings,
            )
            return rtype, written
        except Conflict:
            if attempt:
                raise
            record = await _reload(db, record)
            if record.is_deleted:
                raise SubscriberNotFound(f"no subscriber {uuid!r} on {type_key!r}") from None
    raise AssertionError("unreachable")  # pragma: no cover
