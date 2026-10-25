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

The first-ever row for a period is inserted without the ``WHERE``, so a call
with ``qty > limit`` uses ``add_within_limit`` instead: a plain conditional
``UPDATE`` that never inserts. With no row (``used`` is 0) it is refused; on
a counter an admin credited below zero it is admitted when ``used + qty`` still
fits, exactly what ``check`` answers.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, false, func, or_, select, true, update
from sqlalchemy.dialects import postgresql, sqlite

from sm_billing.constants import ENTITLED_STATUSES
from sm_billing.models import Subscription, UsageEvent, UsagePeriod

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
    provider: bool = False,
) -> Any:
    """Add ``qty`` to the period's counter, only within ``limit`` (``None``:
    always). Returns the new ``used``, or no row when refused.

    ``provider``: ``period`` is the subscription's own. A calendar month
    whose end the subscription's replaces (``_stored_end``) is one too."""
    table = UsagePeriod.__table__
    stmt = _insert(dialect_name)(table).values(
        tenant_id=tenant_id,
        meter=meter,
        period_start=period[0],
        period_end=_stored_end(tenant_id, period),
        used=qty,
        updated_at=now,
        provider_period=true() if provider else _takes_sub_end(tenant_id, period),
    )
    total = table.c.used + stmt.excluded.used
    return stmt.on_conflict_do_update(
        index_elements=[table.c.tenant_id, table.c.meter, table.c.period_start],
        set_={
            "used": total,
            "updated_at": stmt.excluded.updated_at,
            "period_end": _later_end(table, stmt.excluded.period_end),
            "provider_period": or_(table.c.provider_period, stmt.excluded.provider_period),
        },
        where=None if limit is None else total <= limit,
    ).returning(table.c.used)


def _stored_end(tenant_id: str, period: tuple[datetime, datetime]) -> Any:
    """The end to store: ``period``'s, or the subscription's if it is later.

    ``period`` was resolved in an earlier read, so a sync that extended the
    period since (same start, later end) and found no row to extend yet
    would otherwise leave a first row with the stale end. Read in the same
    statement as the write, under ``FOR SHARE`` on Postgres: a sync whose
    subscription update is in flight is waited for (it then updates the
    subscription row before ``extend_rollups``), and a sync that starts after
    this read waits for this write to commit, then extends the row. SQLite
    ignores the lock clause; its single writer already orders the two.

    Only an entitled subscription's end counts: a lapsed one's start can
    coincide with a calendar month's, whose end it is not. That test is in
    the ``CASE``, not the ``WHERE``, so the row is locked whatever its
    status: a consume that resolved a calendar month while the subscription
    was unpaid still waits for the sync that makes it active, then takes
    its end.
    """
    sub_end = Subscription.current_period_end
    later = _subscription(
        tenant_id, period, case((_later_sub_end(period), sub_end), else_=period[1])
    )
    return func.coalesce(later, period[1])


def _later_sub_end(period: tuple[datetime, datetime]) -> Any:
    entitled = Subscription.status.in_(ENTITLED_STATUSES)
    return and_(entitled, Subscription.current_period_end > period[1])


def _takes_sub_end(tenant_id: str, period: tuple[datetime, datetime]) -> Any:
    """Whether ``_stored_end`` takes the subscription's end: the row is then
    that subscription's period, whatever ``period`` was resolved as."""
    return func.coalesce(_subscription(tenant_id, period, _later_sub_end(period)), false())


def _subscription(tenant_id: str, period: tuple[datetime, datetime], column: Any) -> Any:
    """``column`` of the subscription whose period starts at ``period``'s,
    read under ``FOR SHARE`` (see ``_stored_end``)."""
    return (
        select(column)
        .where(Subscription.tenant_id == tenant_id, Subscription.current_period_start == period[0])
        .with_for_update(read=True)
        .scalar_subquery()
    )


def _later_end(table: Any, end: Any) -> Any:
    """The row's ``period_end``, moved out to ``end`` when that is later.

    A provider that extends a period keeps its start, so writes keep landing
    in the same row; its stored end follows the resolved one. It never moves
    in, so a write that resolved the period before a concurrent extension
    cannot undo it.
    """
    return case((end > table.c.period_end, end), else_=table.c.period_end)


def extend_rollups(*, tenant_id: str, start: datetime, end: datetime, entitled: bool) -> Any:
    """Every counter of the tenant's period starting at ``start`` ends at ``end``.

    Run by ``sync.apply_snapshot`` when the provider moves a period's end but
    keeps its start, so the stored end stays authoritative: the period after
    it begins exactly where these rows end.

    ``entitled``: the subscription is in force, so every row starting at
    ``start`` is its period's (a consume writes into it from now on), even
    one written as a calendar month while it lapsed. Otherwise only rows
    written as its period move; a lapse's calendar months keep their end.
    """
    table = UsagePeriod.__table__
    stmt = update(table).where(
        table.c.tenant_id == tenant_id,
        table.c.period_start == start,
        or_(table.c.period_end != end, table.c.provider_period.is_(False)),
    )
    if not entitled:
        stmt = stmt.where(table.c.provider_period.is_(True))
    return stmt.values(period_end=end, provider_period=True)


def add_within_limit(
    *,
    tenant_id: str,
    meter: str,
    start: datetime,
    qty: int,
    limit: int,
    now: datetime,
    end: datetime | None = None,
    provider: bool = False,
) -> Any:
    """Add ``qty`` to an existing counter only ``WHERE used + qty <= limit``.

    For ``qty > limit``, where inserting a fresh row would over-admit. On
    Postgres a concurrent writer's row lock makes this wait and re-check the
    committed row, as the upsert does.
    """
    table = UsagePeriod.__table__
    total = table.c.used + qty
    return (
        update(table)
        .where(
            table.c.tenant_id == tenant_id,
            table.c.meter == meter,
            table.c.period_start == start,
            total <= limit,
        )
        .values(
            used=total,
            updated_at=now,
            period_end=table.c.period_end if end is None else _later_end(table, end),
            provider_period=true() if provider else table.c.provider_period,
        )
        .returning(table.c.used)
    )
