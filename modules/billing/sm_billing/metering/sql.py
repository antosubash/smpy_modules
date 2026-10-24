"""The enforcement primitive: dialect-specific ``INSERT … ON CONFLICT``.

Both statements are single upserts, so the check and the write cannot be
split by a concurrent writer:

- ``insert_event`` claims the idempotency key. ``DO NOTHING`` plus
  ``RETURNING id`` tells a first call (an id) from a replay (no row).
- ``upsert_period`` adds to the counter only ``WHERE used + qty <= limit``.
  On Postgres a concurrent upsert waits on the row lock and the ``WHERE`` is
  re-evaluated against the committed row (the documented ``ON CONFLICT``
  guarantee); on SQLite there is one writer at a time. No row back means
  refused.

The first-ever row for a period is inserted without the ``WHERE``, which is
why the service refuses ``qty > limit`` before it gets here.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from sqlalchemy.dialects import postgresql, sqlite

from sm_billing.models import UsageEvent, UsagePeriod

_INSERTS = {"postgresql": postgresql.insert, "sqlite": sqlite.insert}
# RETURNING arrived in 3.35, as did ON CONFLICT … DO UPDATE … WHERE with it.
SQLITE_MIN = (3, 35)


def ensure_supported(dialect_name: str) -> None:
    """Fail at startup rather than on the first metered request."""
    if dialect_name not in _INSERTS:
        raise NotImplementedError(
            f"billing metering supports postgresql and sqlite, not {dialect_name}"
        )
    if dialect_name == "sqlite" and sqlite3.sqlite_version_info < SQLITE_MIN:
        raise NotImplementedError(
            f"billing metering needs SQLite >= 3.35, this is {sqlite3.sqlite_version}"
        )


def _insert(dialect_name: str) -> Any:
    ensure_supported(dialect_name)
    return _INSERTS[dialect_name]


def insert_event(dialect_name: str, **values: Any) -> Any:
    """Append a ledger row unless its key is taken; returns its id, or no row."""
    table = UsageEvent.__table__
    return (
        _insert(dialect_name)(table)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[table.c.tenant_id, table.c.meter, table.c.idempotency_key]
        )
        .returning(table.c.id)
    )


def upsert_period(
    dialect_name: str,
    *,
    tenant_id: str,
    meter: str,
    period: tuple[datetime, datetime],
    qty: int,
    limit: int | None,
    now: datetime,
) -> Any:
    """Add ``qty`` to the period's counter, only within ``limit`` (``None``:
    always). Returns the new ``used``, or no row when refused."""
    table = UsagePeriod.__table__
    stmt = _insert(dialect_name)(table).values(
        tenant_id=tenant_id,
        meter=meter,
        period_start=period[0],
        period_end=period[1],
        used=qty,
        updated_at=now,
    )
    total = table.c.used + stmt.excluded.used
    return stmt.on_conflict_do_update(
        index_elements=[table.c.tenant_id, table.c.meter, table.c.period_start],
        set_={"used": total, "updated_at": stmt.excluded.updated_at},
        where=None if limit is None else total <= limit,
    ).returning(table.c.used)
