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
  their blocks shorter than the lease, or call :meth:`HeldLock.renew` before
  each SMTP call: it extends the lease, and raises ``DispatchBusy`` once
  another sender has taken the row. Released only by the holder that took
  it (each acquisition stores a holder name with a random suffix).

Not acquired within ``wait_s`` → :class:`~sm_newsletter.core.errors.DispatchBusy`.

**Cancellation.** A cancel (or any other exit) that lands after the first
``pg_try_advisory_lock`` was sent, or during the unlock, may leave the lock
granted on a connection about to go back to the pool, where every later send
would answer ``dispatch_busy`` until it is recycled. So such an exit drops
the connection instead (the lock dies with it). On SQLite the release runs
shielded from a second cancel, and an interrupted acquisition releases too.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

from simple_module_db import finalize_session
from sqlalchemy import or_, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.errors import DispatchBusy
from sm_newsletter.core.upsert import insert_ignore
from sm_newsletter.models import DispatchLock

__all__ = ["ADVISORY_KEY", "LOCK_NAME", "HeldLock", "dispatch_lock"]

logger = logging.getLogger(__name__)

LOCK_NAME = "dispatch"
ADVISORY_KEY = 0x6E6C5F6469737061
"""``"nl_dispa"`` as a signed 64-bit key; fixed, so every process agrees on it."""
POLL_S = 0.1

SessionFactory = Callable[[], AsyncSession]
_TABLE = DispatchLock.__table__  # ty: ignore[unresolved-attribute]


_TRY = text("SELECT pg_try_advisory_lock(:k)")
_UNLOCK = text("SELECT pg_advisory_unlock(:k)")


class HeldLock:
    """What the block receives. :meth:`renew` before each SMTP call: a no-op on
    Postgres (the lock lasts until released), a lease extension on SQLite that
    raises :class:`DispatchBusy` when the lease was lost to another sender."""

    def __init__(self, renew: Callable[[], Awaitable[None]]) -> None:
        self._renew = renew

    async def renew(self) -> None:
        await self._renew()


async def _held_forever() -> None:
    return None


@asynccontextmanager
async def dispatch_lock(
    session_factory: SessionFactory, *, holder: str, wait_s: float = 15, lease_s: float = 120
) -> AsyncIterator[HeldLock]:
    """Hold the dispatch lock for the block; :class:`DispatchBusy` after ``wait_s``."""
    async with session_factory() as probe:
        dialect = probe.get_bind().dialect.name
    if dialect == "postgresql":
        async with _advisory(session_factory, wait_s) as held:
            yield held
    else:
        async with _lock_row(session_factory, holder, wait_s, lease_s) as held:
            yield held


def _deadline(wait_s: float) -> float:
    return time.monotonic() + wait_s


async def _wait_or_give_up(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise DispatchBusy()
    await asyncio.sleep(POLL_S)


@asynccontextmanager
async def _advisory(session_factory: SessionFactory, wait_s: float) -> AsyncIterator[HeldLock]:
    deadline = _deadline(wait_s)
    key = {"k": ADVISORY_KEY}
    async with session_factory() as session:
        conn = await session.connection(execution_options={"isolation_level": "AUTOCOMMIT"})
        try:
            while not await conn.scalar(_TRY, key):
                await _wait_or_give_up(deadline)
        except DispatchBusy:
            raise  # the last try answered no: nothing is held
        except BaseException:
            await _discard(conn)  # a cancelled try may have been granted
            raise
        try:
            yield HeldLock(_held_forever)
        finally:
            try:
                await conn.execute(_UNLOCK, key)
            except Exception:
                logger.warning("newsletter: dispatch lock unlock failed", exc_info=True)
                await _discard(conn)
            except BaseException:
                await _discard(conn)
                raise


async def _discard(conn: AsyncConnection) -> None:
    """Drop ``conn`` for good rather than pool it: the advisory lock dies with it.
    Shielded, so a second cancel cannot stop it half way; that cancel still
    propagates to the caller once logged."""
    try:
        await asyncio.shield(conn.invalidate())
    except asyncio.CancelledError:
        logger.warning("newsletter: cancelled while dropping the dispatch lock's connection")
        raise
    except Exception:
        logger.warning("newsletter: could not drop the dispatch lock's connection", exc_info=True)


@asynccontextmanager
async def _lock_row(
    session_factory: SessionFactory, holder: str, wait_s: float, lease_s: float
) -> AsyncIterator[HeldLock]:
    me = f"{holder[:48]}:{secrets.token_hex(6)}"
    deadline = _deadline(wait_s)
    async with session_factory() as session:
        seed = {"name": LOCK_NAME, "holder": None, "locked_until": None, "updated_at": utcnow()}
        await insert_ignore(session, _TABLE, [seed], conflict=["name"])
        await finalize_session(session)
    try:
        while not await _set_holder(session_factory, me, lease_s, take=True):
            await _wait_or_give_up(deadline)
    except DispatchBusy:
        raise
    except BaseException:
        # A cancelled take may have committed: release whatever ``me`` holds.
        await asyncio.shield(_release(session_factory, me))
        raise

    async def renew() -> None:
        if not await _set_holder(session_factory, me, lease_s, take=False):
            raise DispatchBusy("The dispatch lock was taken over; the rest was not sent")

    try:
        yield HeldLock(renew)
    finally:
        await asyncio.shield(_release(session_factory, me))


async def _set_holder(
    session_factory: SessionFactory, me: str, lease_s: float, *, take: bool
) -> bool:
    """Take the row (free or expired) or, with ``take=False``, extend ``me``'s lease."""
    now = utcnow()
    who = (
        or_(_TABLE.c.holder.is_(None), _TABLE.c.locked_until < now)
        if take
        else _TABLE.c.holder == me
    )
    async with session_factory() as session:
        result = await session.execute(
            update(_TABLE)
            .where(_TABLE.c.name == LOCK_NAME, who)
            .values(holder=me, locked_until=now + timedelta(seconds=lease_s), updated_at=now)
        )
        await finalize_session(session)
    return result.rowcount == 1  # ty: ignore[unresolved-attribute]


async def _release(session_factory: SessionFactory, me: str) -> None:
    async with session_factory() as session:
        await session.execute(
            update(_TABLE)
            .where(_TABLE.c.name == LOCK_NAME, _TABLE.c.holder == me)
            .values(holder=None, locked_until=None, updated_at=utcnow())
        )
        await finalize_session(session)
