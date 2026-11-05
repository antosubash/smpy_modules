"""The install-wide dispatch lock: one sender spends the SMTP budget at a time.

Admission (count the windows, then send) is only safe when nobody else can
count or send in between, so every sender - a test send now, PR 4's dispatcher
later - runs its admission *and* its SMTP calls inside :func:`dispatch_lock`.

- **Postgres**: the session-level advisory lock :data:`ADVISORY_KEY`, polled
  with ``pg_try_advisory_lock`` on one dedicated connection (``AUTOCOMMIT``,
  so it is never idle in a transaction) that is held for the whole block and
  released with ``pg_advisory_unlock``. A crashed holder's lock dies with its
  connection.
- **SQLite**: the ``newsletter_dispatch_lock`` row :data:`LOCK_NAME`, inserted
  on first use and taken by a conditional ``UPDATE`` (free, or its lease
  expired). The lease (``lease_s``) is what frees a crashed holder's row; a
  block that outlives it may lose the lock to the next taker, so callers keep
  their blocks shorter than the lease. Released only by the holder that took
  it (each acquisition stores a holder name with a random suffix).

Not acquired within ``wait_s`` → :class:`~sm_newsletter.core.errors.DispatchBusy`.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

from simple_module_db import finalize_session
from sqlalchemy import or_, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.errors import DispatchBusy
from sm_newsletter.core.upsert import insert_ignore
from sm_newsletter.models import DispatchLock

__all__ = ["ADVISORY_KEY", "LOCK_NAME", "dispatch_lock"]

logger = logging.getLogger(__name__)

LOCK_NAME = "dispatch"
ADVISORY_KEY = 0x6E6C5F6469737061
"""``"nl_dispa"`` as a signed 64-bit key; fixed, so every process agrees on it."""
POLL_S = 0.1

SessionFactory = Callable[[], AsyncSession]
_TABLE = DispatchLock.__table__  # ty: ignore[unresolved-attribute]


@asynccontextmanager
async def dispatch_lock(
    session_factory: SessionFactory, *, holder: str, wait_s: float = 15, lease_s: float = 120
) -> AsyncIterator[None]:
    """Hold the dispatch lock for the block; :class:`DispatchBusy` after ``wait_s``."""
    async with session_factory() as probe:
        dialect = probe.get_bind().dialect.name
    if dialect == "postgresql":
        async with _advisory(session_factory, wait_s):
            yield
    else:
        async with _lock_row(session_factory, holder, wait_s, lease_s):
            yield


def _deadline(wait_s: float) -> float:
    return time.monotonic() + wait_s


async def _wait_or_give_up(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise DispatchBusy()
    await asyncio.sleep(POLL_S)


@asynccontextmanager
async def _advisory(session_factory: SessionFactory, wait_s: float) -> AsyncIterator[None]:
    deadline = _deadline(wait_s)
    async with session_factory() as session:
        conn = await session.connection(execution_options={"isolation_level": "AUTOCOMMIT"})
        key = {"k": ADVISORY_KEY}
        while not await conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), key):
            await _wait_or_give_up(deadline)
        try:
            yield
        finally:
            try:
                await conn.execute(text("SELECT pg_advisory_unlock(:k)"), key)
            except Exception:
                # Never hand a connection that may still hold the lock back to
                # the pool: dropping it is what releases the lock.
                logger.warning("newsletter: dispatch lock unlock failed", exc_info=True)
                await conn.invalidate()


@asynccontextmanager
async def _lock_row(
    session_factory: SessionFactory, holder: str, wait_s: float, lease_s: float
) -> AsyncIterator[None]:
    me = f"{holder[:48]}:{secrets.token_hex(6)}"
    deadline = _deadline(wait_s)
    async with session_factory() as session:
        seed = {"name": LOCK_NAME, "holder": None, "locked_until": None, "updated_at": utcnow()}
        await insert_ignore(session, _TABLE, [seed], conflict=["name"])
        await finalize_session(session)
    while not await _take(session_factory, me, lease_s):
        await _wait_or_give_up(deadline)
    try:
        yield
    finally:
        async with session_factory() as session:
            await session.execute(
                update(_TABLE)
                .where(_TABLE.c.name == LOCK_NAME, _TABLE.c.holder == me)
                .values(holder=None, locked_until=None, updated_at=utcnow())
            )
            await finalize_session(session)


async def _take(session_factory: SessionFactory, me: str, lease_s: float) -> bool:
    now = utcnow()
    async with session_factory() as session:
        result = await session.execute(
            update(_TABLE)
            .where(
                _TABLE.c.name == LOCK_NAME,
                or_(_TABLE.c.holder.is_(None), _TABLE.c.locked_until < now),
            )
            .values(holder=me, locked_until=now + timedelta(seconds=lease_s), updated_at=now)
        )
        await finalize_session(session)
    return result.rowcount == 1  # ty: ignore[unresolved-attribute]
