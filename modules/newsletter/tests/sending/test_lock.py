"""The install-wide dispatch lock, on SQLite (lock row) and Postgres (advisory lock).

Each test uses a file database on SQLite, so the two holders have connections
of their own, as they would on a host.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from simple_module_db import finalize_session
from sm_newsletter.core.errors import DispatchBusy
from sm_newsletter.models import DispatchLock
from sm_newsletter.sending.lock import LOCK_NAME, dispatch_lock
from sqlalchemy import select, update

from tests.pg_support import USING_POSTGRES, make_db_state


@pytest_asyncio.fixture
async def state(tmp_path):
    db_state = await make_db_state(file=tmp_path / "lock.db")
    yield db_state
    await db_state.engine.dispose()


async def test_second_holder_waits_then_is_busy(state):
    factory = state.session_factory
    async with dispatch_lock(factory, holder="first", wait_s=1):
        with pytest.raises(DispatchBusy):
            async with dispatch_lock(factory, holder="second", wait_s=0.3):
                pytest.fail("acquired a held lock")


async def test_released_after_the_block_even_on_error(state):
    factory = state.session_factory
    with pytest.raises(RuntimeError):
        async with dispatch_lock(factory, holder="first", wait_s=1):
            raise RuntimeError("boom")
    async with dispatch_lock(factory, holder="second", wait_s=0.3):
        pass


async def test_waiter_gets_it_when_released(state):
    factory = state.session_factory
    order: list[str] = []

    async def hold() -> None:
        async with dispatch_lock(factory, holder="first", wait_s=1):
            order.append("first in")
            await asyncio.sleep(0.3)
            order.append("first out")

    async def wait() -> None:
        await asyncio.sleep(0.05)
        async with dispatch_lock(factory, holder="second", wait_s=3):
            order.append("second in")

    await asyncio.gather(hold(), wait())
    assert order == ["first in", "first out", "second in"]


@pytest.mark.skipif(USING_POSTGRES, reason="the lease is the SQLite lock row's")
async def test_sqlite_expired_lease_is_taken_over(state):
    factory = state.session_factory

    async def holder() -> str | None:
        async with factory() as db:
            return (await db.execute(select(DispatchLock.holder))).scalar_one()

    first = dispatch_lock(factory, holder="first", wait_s=1)
    await first.__aenter__()
    async with factory() as db:
        past = datetime.now(UTC) - timedelta(seconds=1)
        await db.execute(
            update(DispatchLock).where(DispatchLock.name == LOCK_NAME).values(locked_until=past)
        )
        await finalize_session(db)
    second = dispatch_lock(factory, holder="second", wait_s=0.3)
    await second.__aenter__()
    assert (await holder() or "").startswith("second:")
    # The first holder's release does not free the lock the second one took.
    await first.__aexit__(None, None, None)
    assert (await holder() or "").startswith("second:")
    await second.__aexit__(None, None, None)
    assert await holder() is None


async def test_cancelled_inside_the_block_releases(state):
    factory = state.session_factory
    entered = asyncio.Event()

    async def hold() -> None:
        async with dispatch_lock(factory, holder="first", wait_s=1):
            entered.set()
            await asyncio.sleep(30)

    task = asyncio.create_task(hold())
    await entered.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    async with dispatch_lock(factory, holder="second", wait_s=0.5):
        pass


async def test_cancelled_while_acquiring_never_leaks(state):
    """Cancel after 0..N scheduler steps, so some cancels land mid-query
    (on Postgres, possibly after the server granted the lock)."""
    factory = state.session_factory

    async def take() -> None:
        async with dispatch_lock(factory, holder="racer", wait_s=1):
            await asyncio.sleep(30)

    for steps in range(25):
        task = asyncio.create_task(take())
        for _ in range(steps):
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        async with dispatch_lock(factory, holder="after", wait_s=1):
            pass


@pytest.mark.skipif(USING_POSTGRES, reason="the lease is the SQLite lock row's")
async def test_sqlite_renew_extends_or_reports_the_loss(state):
    factory = state.session_factory

    async def until() -> datetime:
        async with factory() as db:
            return (await db.execute(select(DispatchLock.locked_until))).scalar_one()

    async with dispatch_lock(factory, holder="me", wait_s=1, lease_s=60) as held:
        before = await until()
        await asyncio.sleep(0.01)
        await held.renew()
        assert await until() > before
        async with factory() as db:
            await db.execute(update(DispatchLock).values(holder="thief:1"))
            await finalize_session(db)
        with pytest.raises(DispatchBusy):
            await held.renew()
    async with factory() as db:
        assert (await db.execute(select(DispatchLock.holder))).scalar_one() == "thief:1"


@pytest.mark.skipif(not USING_POSTGRES, reason="the advisory lock's renew")
async def test_postgres_renew_is_a_no_op(state):
    async with dispatch_lock(state.session_factory, holder="me", wait_s=1) as held:
        await held.renew()


async def test_cancel_while_discarding_propagates():
    # I3: a cancel that lands while the connection is being dropped must not
    # be swallowed, or the task keeps running after its caller cancelled it.
    from sm_newsletter.sending.lock import _discard

    started = asyncio.Event()

    class _SlowConn:
        async def invalidate(self) -> None:
            started.set()
            await asyncio.sleep(10)

    task = asyncio.create_task(_discard(_SlowConn()))  # ty: ignore[invalid-argument-type]
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_discard_logs_a_failed_invalidate():
    from sm_newsletter.sending.lock import _discard

    class _BrokenConn:
        async def invalidate(self) -> None:
            raise RuntimeError("gone")

    await _discard(_BrokenConn())  # ty: ignore[invalid-argument-type]


async def _lock_row(factory) -> tuple[str | None, datetime | None]:
    async with factory() as db:
        row = (await db.execute(select(DispatchLock.holder, DispatchLock.locked_until))).one()
        return row[0], row[1]


async def _fence(held, factory) -> None:
    async with factory() as db:
        try:
            await held.fence(db)
        except DispatchBusy:
            await db.rollback()
            raise
        await finalize_session(db)


@pytest.mark.skipif(USING_POSTGRES, reason="the lease is the SQLite lock row's")
async def test_fence_inside_transaction(state):
    factory = state.session_factory
    async with dispatch_lock(factory, holder="me", wait_s=1, lease_s=60) as held:
        _, before = await _lock_row(factory)
        await asyncio.sleep(0.01)
        await _fence(held, factory)
        me, after = await _lock_row(factory)
        assert after is not None and before is not None and after > before
        past = datetime.now(UTC) - timedelta(seconds=1)
        async with factory() as db:
            await db.execute(update(DispatchLock).values(locked_until=past))
            await finalize_session(db)
        with pytest.raises(DispatchBusy):
            await _fence(held, factory)  # expired, even though still named holder
        future = datetime.now(UTC) + timedelta(seconds=60)
        async with factory() as db:
            await db.execute(update(DispatchLock).values(holder="thief:1", locked_until=future))
            await finalize_session(db)
        with pytest.raises(DispatchBusy):
            await _fence(held, factory)
        assert (await _lock_row(factory))[0] == "thief:1"  # the fence took nothing back
    assert me is not None and me.startswith("me:")


@pytest.mark.skipif(not USING_POSTGRES, reason="the advisory lock's fence")
async def test_postgres_fence_is_a_no_op(state):
    lock = dispatch_lock(state.session_factory, holder="me", wait_s=1)
    async with lock as held, state.session_factory() as db:
        await held.fence(db)
        await finalize_session(db)
