"""Unconfirmed holds: how long a pending registration keeps its seat, and how many may exist.

A pending (double opt-in, unconfirmed) registration takes a seat at once, which is what makes
"fill an event with addresses nobody confirms" possible. Two bounds close it:

* **Time.** A pending registration holds its seat for the type's ``pending_hold_hours`` (default
  one hour, at least one, at most a week). The retention sweep purges it afterwards through the
  normal paths (which release the seat), and, so a full event does not wait for the next sweep, the
  next person to register for the same occurrence purges that occurrence's expired holds first
  (bounded by ``EXPIRE_BATCH``), under the type lock they already hold and in the same transaction.
  Its confirm link stops working at the same moment.
* **Count.** At most :func:`pending_cap` unconfirmed holds exist per occurrence: half the capacity
  (at least one), never more than ``MAX_PENDING``. A registration over it is told "try later" by
  mail (the same 202 as every other answer); a confirmed registration is never counted or touched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import bound_tenant
from sm_records.models import Record, RecordType, tables_for
from sm_records.public_submissions.registration.tokens import RegistrationToken
from sm_records.public_submissions.retention_rules import PENDING
from sm_records.records.index.query import Filter, FilterOp, filtered
from sm_records.records.services._common import utcnow
from sm_records.records.services.records import hard_delete_record, soft_delete_record

__all__ = [
    "EXPIRE_BATCH",
    "MAX_PENDING",
    "MAX_SCAN",
    "expire_pending",
    "pending_cap",
    "pending_for",
]

MAX_PENDING: Final = 25
"""The most unconfirmed holds one occurrence may carry, whatever its capacity."""
MAX_SCAN: Final = 500
"""The most pending registrations of one occurrence read at once (far above any cap)."""
EXPIRE_BATCH: Final = 50
"""The most expired holds one registration purges on the way."""


def _now() -> datetime:
    return utcnow()


def pending_cap(capacity: int | None) -> int:
    """Half the seats (at least one), at most ``MAX_PENDING``; unlimited capacity: the maximum."""
    if capacity is None:
        return MAX_PENDING
    return min(MAX_PENDING, max(1, capacity // 2))


def _moment(value: Any) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


async def pending_for(
    db: AsyncSession, rtype: RecordType, token: RegistrationToken
) -> list[Record]:
    """The live ``pending`` registrations of this occurrence (the type lock is the caller's)."""
    cls = tables_for(rtype).record
    tenant = bound_tenant()
    stmt = filtered(
        select(cls).where(cls.type_id == rtype.id, cls.tenant_id == tenant),
        rtype,
        list(rtype.fields or []),
        [
            Filter("sm_event_id", FilterOp.EQ, token.event_id),
            Filter("sm_occurrence_key", FilterOp.EQ, token.occurrence_key),
            Filter("sm_status", FilterOp.EQ, PENDING),
        ],
    ).limit(MAX_SCAN)
    return [
        r for r in (await db.execute(stmt)).scalars() if (r.data or {}).get("sm_status") == PENDING
    ]


async def expire_pending(
    db: AsyncSession,
    rtype: RecordType,
    token: RegistrationToken,
    settings: RecordsSettings,
) -> list[Record]:
    """Purge this occurrence's expired pending holds (their seats go with them); the pending
    registrations that remain. Runs under the type lock, in the registering transaction."""
    hold = timedelta(hours=int((rtype.public_submissions or {}).get("pending_hold_hours") or 1))
    now = _now()
    live = await pending_for(db, rtype, token)
    expired = [
        r
        for r in live
        if (when := _moment((r.data or {}).get("sm_consent_at") or r.created_at)) is not None
        and when + hold < now
    ][:EXPIRE_BATCH]
    for record in expired:
        await soft_delete_record(db, rtype, record, settings=settings)
        await hard_delete_record(db, rtype, record)
    gone = {r.uuid for r in expired}
    return [r for r in live if r.uuid not in gone]
