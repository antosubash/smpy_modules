"""The counter rows' locks and recount: the shared half of admit, release and release_target.

See :mod:`sm_events.registration.seats` for the lock order these implement.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.dialects import postgresql, sqlite

from sm_events.models import RegistrationCount, RegistrationSeat

__all__ = [
    "COUNT",
    "COUNT_KEY",
    "SEAT",
    "SEAT_KEY",
    "insert_for",
    "lock_counter",
    "lock_counters",
    "recount",
]

COUNT = RegistrationCount.__table__  # type: ignore[attr-defined]
SEAT = RegistrationSeat.__table__  # type: ignore[attr-defined]
COUNT_KEY = ["tenant_id", "event_id", "occurrence_key"]
SEAT_KEY = ["tenant_id", "provider", "holder"]
_KEYS_PER_STATEMENT = 200


def insert_for(db: Any) -> Any:
    """The dialect's ``insert`` (both have ``ON CONFLICT DO NOTHING ... RETURNING``)."""
    return postgresql.insert if db.bind.dialect.name == "postgresql" else sqlite.insert


async def lock_counter(db: Any, tenant: str, event_id: uuid.UUID, key: str, now: datetime) -> int:
    """Make sure the occurrence's counter row exists, then take its row lock; its id."""
    await db.execute(
        insert_for(db)(COUNT)
        .values(tenant_id=tenant, event_id=event_id, occurrence_key=key, taken=0, updated_at=now)
        .on_conflict_do_nothing(index_elements=COUNT_KEY)
    )
    found = await db.execute(
        select(COUNT.c.id)
        .where(
            COUNT.c.tenant_id == tenant,
            COUNT.c.event_id == event_id,
            COUNT.c.occurrence_key == key,
        )
        .with_for_update()
    )
    return found.scalar_one()


async def recount(db: Any, tenant: str, counter_ids: Sequence[int], now: datetime) -> None:
    """Set each counter to the number of seat rows it counts (its lock is already ours)."""
    seen = (
        select(func.count())
        .select_from(SEAT)
        .where(
            SEAT.c.tenant_id == COUNT.c.tenant_id,
            SEAT.c.event_id == COUNT.c.event_id,
            SEAT.c.occurrence_key == COUNT.c.occurrence_key,
        )
        .correlate(COUNT)
        .scalar_subquery()
    )
    for start in range(0, len(counter_ids), _KEYS_PER_STATEMENT):
        chunk = counter_ids[start : start + _KEYS_PER_STATEMENT]
        await db.execute(
            update(COUNT)
            .where(COUNT.c.tenant_id == tenant, COUNT.c.id.in_(chunk))
            .values(taken=seen, updated_at=now)
        )


async def lock_counters(
    db: Any, tenant: str, keys: Sequence[tuple[uuid.UUID, str]]
) -> list[tuple[int, uuid.UUID, str]]:
    """Lock these occurrences' counter rows, in ascending id (one order for everybody), and say
    which ones exist: ``(id, event_id, occurrence_key)``. A key with no counter row is absent: no
    seat of it may be touched, because nothing holds its lock."""
    found: list[tuple[int, uuid.UUID, str]] = []
    for start in range(0, len(keys), _KEYS_PER_STATEMENT):
        pairs = list(keys[start : start + _KEYS_PER_STATEMENT])
        rows = await db.execute(
            select(COUNT.c.id, COUNT.c.event_id, COUNT.c.occurrence_key)
            .where(
                COUNT.c.tenant_id == tenant,
                tuple_(COUNT.c.event_id, COUNT.c.occurrence_key).in_(pairs),
            )
            .order_by(COUNT.c.id)
            .with_for_update()
        )
        found.extend((i, e, k) for i, e, k in rows.all())
    return sorted(found)
