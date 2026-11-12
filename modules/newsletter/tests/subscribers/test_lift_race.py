"""A lift and a records unsubscribe of the same subscriber serialise (C2).

Both take the subscriber's row lock first (records' ``lock_record``), then the
suppression row. No mirror handler is registered: records' contract
``unsubscribe`` gets no bus, so nothing re-suppresses behind the test's back.
The unsubscribe-first race needs two real transactions and runs on Postgres;
the lift-first ordering runs on SQLite too, on a file database (one connection
per session), where the lift's write lock is what the unsubscribe waits for.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from simple_module_db import finalize_session
from sm_newsletter.core.errors_audience import OptOutStands
from sm_newsletter.core.suppression.reconcile import reconcile_async
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.subscribers.lift import lift
from sm_newsletter.subscribers.suppressions import rows_for_email
from sm_records.contracts.newsletter import unsubscribe

from tests.pg_support import USING_POSTGRES, make_db_state
from tests.support.lift_world import lifts, purge, rows, seed_row, status_of
from tests.support.records_seed import RECORDS_APP, seed_list, seed_subscriber

pytestmark = pytest.mark.unbound_tenant

ADA = "ada@example.org"
NOW = datetime.now(UTC)
WAIT_S = 10


@pytest_asyncio.fixture
async def world(tmp_path):
    """Case (b): an ``unsubscribed`` row on ``news`` and the address confirmed
    later on a fresh record; ``(db_state, row, uuid)``."""
    state = await make_db_state(file=tmp_path / "race.sqlite")
    await seed_list(state, "default")
    await seed_row(state, "default", ADA, "unsubscribed", key="news", at=NOW - timedelta(hours=1))
    old = await seed_subscriber(state, "default", ADA, "unsubscribed")
    await purge(state, "default", old)
    uuid = await seed_subscriber(state, "default", ADA, "confirmed")
    async with state.session_factory() as s:
        [row] = await rows_for_email(s, tenant_id="default", roles=None, email=ADA)
    yield state, row, uuid
    await state.engine.dispose()


async def _unsubscribe(session, uuid: str) -> bool:
    return await unsubscribe(
        session,
        tenant_id="default",
        type_key="news",
        uuid=uuid,
        unless_confirmed_after=None,
        app=RECORDS_APP,
    )


async def _lift(session, row):
    return await lift(
        session,
        tenant_id="default",
        roles=None,
        suppression_id=row.id,
        version=row.version,
        email=ADA,
        note="re-subscribed by phone",
        now=NOW,
    )


@pytest.mark.skipif(not USING_POSTGRES, reason="two real transactions need Postgres")
async def test_concurrent_unsubscribe_wins_and_lift_keeps_protection(world):
    state, row, uuid = world
    with tenant_scope("default"):
        async with state.session_factory() as first, state.session_factory() as second:
            assert await _unsubscribe(first, uuid) is True  # holds the row lock

            async def lifting():
                try:
                    return await _lift(second, row)
                finally:
                    await second.rollback()

            task = asyncio.create_task(lifting())
            await asyncio.sleep(0.3)
            assert not task.done()  # blocked in lock_confirmation
            await finalize_session(first)
            with pytest.raises(OptOutStands):
                await asyncio.wait_for(task, WAIT_S)
    assert len(await rows(state)) == 1
    assert await lifts(state) == []
    assert await status_of(state, "default", uuid) == "unsubscribed"


async def test_lift_first_then_unsubscribe_serialises(world):
    state, row, uuid = world
    with tenant_scope("default"):
        async with state.session_factory() as first, state.session_factory() as second:
            await _lift(first, row)  # holds the row lock and the suppression delete

            async def leaving() -> bool:
                wrote = await _unsubscribe(second, uuid)
                await finalize_session(second)
                return wrote

            task = asyncio.create_task(leaving())
            await asyncio.sleep(0.3)
            assert not task.done()
            await finalize_session(first)
            assert await asyncio.wait_for(task, WAIT_S) is True
    assert len(await lifts(state)) == 1
    assert await status_of(state, "default", uuid) == "unsubscribed"
    assert await rows(state) == []
    result = await reconcile_async(state.session_factory, now=NOW)
    assert result["suppressed"] == 1
    assert [(r.reason, r.list_type_key) for r in await rows(state)] == [("unsubscribed", "news")]
