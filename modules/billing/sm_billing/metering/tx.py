"""How a metering write is wrapped: its own transaction, or a caller's savepoint.

Own sessions end with ``finalize_session``, never a bare ``commit()`` (the
billing rule: a ``RequestSession`` runs its ``on_commit`` work only there).
With ``db=`` the write runs inside ``db.begin_nested()``, so a refusal or a
replay rolls back only the metering and the caller's transaction carries on;
the framework's outermost-SAVEPOINT listener (GH #350) makes that safe on
SQLite.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from simple_module_db import finalize_session, mark_written
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from sm_billing.metering.errors import UsageBusyError, is_sqlite_busy
from sm_billing.models import UsageEvent, UsagePeriod

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Apply = Callable[["AsyncSession"], Awaitable[Any]]


@dataclass(frozen=True)
class Counted:
    """What an ``apply`` returns to keep its writes: the counter's new value
    (and, for a period counter, its stored end)."""

    used: int
    end: datetime | None = field(default=None, kw_only=True)


@dataclass(frozen=True)
class Terminal:
    """What an ``apply`` returns to keep its writes when they record a key's
    terminal outcome - a refusal, an expired call, a closed key - rather than
    a count: ``outcome`` is what the call answers."""

    outcome: Any


def _keeps(outcome: Any) -> bool:
    return isinstance(outcome, (Counted, Terminal))


class _Undo(Exception):  # noqa: N818 - control flow, never escapes this module
    """Roll the savepoint back but keep the caller's transaction."""


async def _in_savepoint(db: AsyncSession, apply: Apply) -> Any:
    outcome = None
    try:
        async with db.begin_nested():
            outcome = await apply(db)
            if not _keeps(outcome):
                raise _Undo
    except _Undo:
        return outcome
    mark_written(db)
    return outcome


async def run_write(factory: async_sessionmaker, db: AsyncSession | None, apply: Apply) -> Any:
    """Run ``apply`` and keep its writes only when it returns ``Counted`` or
    ``Terminal`` (a key's recorded outcome: hold, refusal, expiry, closure).

    Anything else (a replay, a refusal that records nothing) is rolled back. SQLite's "database is
    locked" becomes ``UsageBusyError`` (503): the call fails closed.
    """
    try:
        if db is not None:
            return await _in_savepoint(db, apply)
        async with factory() as session:
            outcome = await apply(session)
            if _keeps(outcome):
                # Core DML: flag it, or finalize_session sees nothing to commit.
                mark_written(session)
                await finalize_session(session)
            else:
                await session.rollback()
            return outcome
    except OperationalError as exc:
        if is_sqlite_busy(exc):
            raise UsageBusyError() from exc
        raise


async def period_row(session: AsyncSession, tenant_id: str, meter: str, start: datetime):
    """``(used, period_end)`` as columns, not an entity: in a joined session an
    identity-mapped row would not show the upsert's change."""
    stmt = select(UsagePeriod.used, UsagePeriod.period_end).where(
        UsagePeriod.tenant_id == tenant_id,
        UsagePeriod.meter == meter,
        UsagePeriod.period_start == start,
    )
    return (await session.execute(stmt)).one_or_none()


async def find_event(session: AsyncSession, tenant_id: str, meter: str, key: str):
    stmt = select(UsageEvent).where(
        UsageEvent.tenant_id == tenant_id,
        UsageEvent.meter == meter,
        UsageEvent.idempotency_key == key,
    )
    return (await session.execute(stmt)).scalar_one_or_none()
