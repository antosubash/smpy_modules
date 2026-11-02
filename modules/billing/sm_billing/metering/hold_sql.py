"""The gauge statements: the same one-statement primitives as ``metering.sql``.

- ``insert_hold`` claims the idempotency key (``DO NOTHING RETURNING id``).
- ``upsert_gauge`` raises the level only ``WHERE in_use + qty <= limit``; the
  first-ever row is inserted without that ``WHERE``, so ``qty > limit`` uses
  ``raise_within_limit``, a conditional ``UPDATE`` that never inserts.
- ``settle`` is the guarded transition every release and expiry goes
  through: ``UPDATE … WHERE id = :id AND status IN (…) RETURNING``. Only the
  call that moved the row gets it back, so two releases, or two sweepers on
  two instances, return the capacity exactly once.
- ``recount`` rebuilds the level from the live holds, after ``touch_gauge``
  took the row lock, so on Postgres its sum is read with a snapshot taken
  after any concurrent reserve on the row committed.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update

from sm_billing.contracts.metering import LIVE_HOLD_STATUSES
from sm_billing.metering.sql import _insert
from sm_billing.models import UsageGauge, UsageHold

HOLD = UsageHold.__table__
GAUGE = UsageGauge.__table__
HOLD_COLUMNS = (
    HOLD.c.id,
    HOLD.c.tenant_id,
    HOLD.c.meter,
    HOLD.c.quantity,
    HOLD.c.status,
    HOLD.c.expires_at,
)


def insert_hold(dialect_name: str, **values: Any) -> Any:
    return (
        _insert(dialect_name)(HOLD)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[HOLD.c.tenant_id, HOLD.c.meter, HOLD.c.idempotency_key]
        )
        .returning(HOLD.c.id)
    )


def upsert_gauge(
    dialect_name: str, *, tenant_id: str, meter: str, qty: int, limit: int | None, now: datetime
) -> Any:
    """Add ``qty`` to the level within ``limit``; the new level, or no row."""
    stmt = _insert(dialect_name)(GAUGE).values(
        tenant_id=tenant_id, meter=meter, in_use=qty, updated_at=now
    )
    total = GAUGE.c.in_use + stmt.excluded.in_use
    return stmt.on_conflict_do_update(
        index_elements=[GAUGE.c.tenant_id, GAUGE.c.meter],
        set_={"in_use": total, "updated_at": stmt.excluded.updated_at},
        where=None if limit is None else total <= limit,
    ).returning(GAUGE.c.in_use)


def gauge_of(tenant_id: str, meter: str) -> tuple:
    return GAUGE.c.tenant_id == tenant_id, GAUGE.c.meter == meter


def raise_within_limit(*, tenant_id: str, meter: str, qty: int, limit: int, now: datetime) -> Any:
    total = GAUGE.c.in_use + qty
    return (
        update(GAUGE)
        .where(*gauge_of(tenant_id, meter), total <= limit)
        .values(in_use=total, updated_at=now)
        .returning(GAUGE.c.in_use)
    )


def lower_gauge(*, tenant_id: str, meter: str, qty: int, now: datetime) -> Any:
    return (
        update(GAUGE)
        .where(*gauge_of(tenant_id, meter))
        .values(in_use=GAUGE.c.in_use - qty, updated_at=now)
    )


def settle(hold_id: str, *, to: str, from_: Iterable[str], now: datetime, due: bool) -> Any:
    """Move a hold out of ``from_``; ``due`` also requires it to have lapsed
    (the sweeper's expiry, which a concurrent ``extend`` must win against)."""
    where = [HOLD.c.id == hold_id, HOLD.c.status.in_(list(from_))]
    if due:
        where.append(HOLD.c.expires_at <= now)
    return update(HOLD).where(*where).values(status=to, settled_at=now).returning(*HOLD_COLUMNS)


def touch_gauge(dialect_name: str, *, tenant_id: str, meter: str, now: datetime) -> Any:
    """Create the row if missing and take its lock (``recount``'s first step)."""
    stmt = _insert(dialect_name)(GAUGE).values(
        tenant_id=tenant_id, meter=meter, in_use=0, updated_at=now
    )
    return stmt.on_conflict_do_update(
        index_elements=[GAUGE.c.tenant_id, GAUGE.c.meter], set_={"updated_at": now}
    )


def recount(*, tenant_id: str, meter: str, now: datetime) -> Any:
    live = (
        select(func.coalesce(func.sum(HOLD.c.quantity), 0))
        .where(
            HOLD.c.tenant_id == tenant_id,
            HOLD.c.meter == meter,
            HOLD.c.status.in_(sorted(LIVE_HOLD_STATUSES)),
        )
        .scalar_subquery()
    )
    return (
        update(GAUGE)
        .where(*gauge_of(tenant_id, meter))
        .values(in_use=live, updated_at=now)
        .returning(GAUGE.c.in_use)
    )
