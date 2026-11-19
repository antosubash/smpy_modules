"""The ledger rows already written for some events and a window of starts."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select

from sm_events.core.tenancy import bound_tenant
from sm_events.models import ReminderSent

__all__ = ["ledger_keys", "utc"]

_L = ReminderSent.__table__


def utc(value: datetime) -> datetime:
    """A stored instant as read back (SQLite drops the zone), for comparing with a computed one."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def ledger_keys(
    db: Any, lead: int, event_ids: Sequence[uuid.UUID], lo: datetime, hi: datetime,
    *, reclaimable_before: datetime | None = None,
) -> set[tuple[uuid.UUID, str, datetime, str]]:  # fmt: skip
    """``(event, occurrence key, start, recipient)`` of the ledger rows for this lead among these
    events starting in ``[lo, hi)``. With ``reclaimable_before``, a ``claimed`` row older than it
    (its lease expired, so another tick may take it over) is not counted."""
    where = [
        _L.c.tenant_id == bound_tenant(),
        _L.c.lead_minutes == lead,
        _L.c.event_id.in_(list(event_ids)),
        _L.c.starts_at >= lo,
        _L.c.starts_at < hi,
    ]
    if reclaimable_before is not None:
        where.append(or_(_L.c.state != "claimed", _L.c.claimed_at >= reclaimable_before))
    stmt = select(_L.c.event_id, _L.c.occurrence_key, _L.c.starts_at, _L.c.recipient_id)
    return {(r[0], r[1], utc(r[2]), r[3]) for r in await db.execute(stmt.where(*where))}
