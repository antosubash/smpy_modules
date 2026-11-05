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
