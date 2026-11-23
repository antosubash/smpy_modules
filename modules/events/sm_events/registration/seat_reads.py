"""Reads of the seat tables: the reconciliation page and the editor's counts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.registration import args
from sm_events.registration.counters import COUNT, SEAT

__all__ = ["SeatRef", "counts", "seat_holders"]


@dataclass(frozen=True)
class SeatRef:
    holder: str
    event_id: uuid.UUID
    occurrence_key: str


async def seat_holders(
    db: Any, *, tenant_id: str, provider: str, after: str | None, limit: int
) -> list[SeatRef]:
    """A page of seats, by holder, strictly after ``after``: for reconciliation. Personal data stays
    where it is: a holder is the provider's own opaque id."""
    who = args.text(provider, "provider", maximum=constants.REGISTRATION_PROVIDER_MAX)
    size = args.bounded_int(limit, "limit", low=1, high=constants.SEAT_HOLDERS_MAX)
    cursor = None if after is None else args.holder(after)
    with tenant_scope(tenant_id) as tenant:
        stmt = (
            select(SEAT.c.holder, SEAT.c.event_id, SEAT.c.occurrence_key)
            .where(SEAT.c.tenant_id == tenant, SEAT.c.provider == who)
            .order_by(SEAT.c.holder)
            .limit(size)
        )
        if cursor is not None:
            stmt = stmt.where(SEAT.c.holder > cursor)
        return [SeatRef(h, e, k) for h, e, k in (await db.execute(stmt)).all()]


async def counts(db: Any, *, tenant_id: str, event_id: uuid.UUID | str) -> list[tuple[str, int]]:
    """``(occurrence key, seats taken)`` of the occurrences of one event that hold any, by key
    (which is chronological), at most ``REGISTRATION_COUNTS_MAX``. The editor's read."""
    eid = args.event_id(event_id)
    with tenant_scope(tenant_id) as tenant:
        stmt = (
            select(COUNT.c.occurrence_key, COUNT.c.taken)
            .where(COUNT.c.tenant_id == tenant, COUNT.c.event_id == eid, COUNT.c.taken > 0)
            .order_by(COUNT.c.occurrence_key)
            .limit(constants.REGISTRATION_COUNTS_MAX)
        )
        return [(key, taken) for key, taken in (await db.execute(stmt)).all()]
