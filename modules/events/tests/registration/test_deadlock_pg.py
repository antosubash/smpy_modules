"""Two transactions releasing the same occurrences in opposite orders (Postgres).

Each ``release`` call locks ascending *within itself*; two calls in one transaction can still cross
another transaction's. The database detects the cycle and aborts one: that must reach the caller
as ``SeatsBusy`` (retry), never as a driver error (a 500).
"""

from __future__ import annotations

import asyncio

import pytest
from sm_events.contracts import registration as contract
from sm_events.core.errors_registration import SeatsBusy
from sm_events.core.tenancy import tenant_scope

from tests.pg_support import USING_POSTGRES
from tests.registration.test_seats_pg import NOW, final, seeded, try_admit
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID

pytestmark = pytest.mark.skipif(not USING_POSTGRES, reason="needs real concurrent transactions")
TIMEOUT = 60


def day(event_id, n):
    return f"{event_id}:2026070{n}T080000Z"


async def release_in_order(state, first, second, barrier, outcome):
    with tenant_scope("default"):
        async with state.session_factory() as db:
            try:
                await contract.release(
                    db, tenant_id="default", provider=PROVIDER_ID, holders=[first]
                )
                await barrier.wait()  # both hold their first counter
                await contract.release(
                    db, tenant_id="default", provider=PROVIDER_ID, holders=[second]
                )
                await db.commit()
                outcome.append("committed")
            except SeatsBusy:
                outcome.append("busy")
                await db.rollback()


async def test_a_deadlock_between_two_releases_is_seats_busy_pg(db_state):
    event_id, _ = await seeded(db_state, capacity=5, series_event=True, rule="FREQ=DAILY")
    a, b = day(event_id, 1), day(event_id, 2)
    await try_admit(db_state, event_id, a, "ha")
    await try_admit(db_state, event_id, b, "hb")
    barrier = asyncio.Barrier(2)
    outcome: list[str] = []
    await asyncio.wait_for(
        asyncio.gather(
            release_in_order(db_state, "ha", "hb", barrier, outcome),
            release_in_order(db_state, "hb", "ha", barrier, outcome),
        ),
        TIMEOUT,
    )
    assert sorted(outcome) == ["busy", "committed"]  # one was the victim; it was told to retry
    counters, holders = await final(db_state)  # recomputed from the rows
    assert holders == [] and sum(counters.values()) == 0  # the survivor freed both; victim's undone


async def test_a_session_without_the_framework_listeners_still_commits_pg(db_state):
    """Core DML on a bare ``Table`` is only committed by ``finalize_session`` if the session was
    marked written; a plain sessionmaker has no listeners to do it, so admit and release mark it
    themselves (PR 8's lease claims were silently rolled back without this)."""
    from simple_module_db import finalize_session
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    event_id, _ = await seeded(db_state, capacity=3, series_event=True, rule="FREQ=DAILY")
    key = day(event_id, 1)
    plain = async_sessionmaker(db_state.engine, class_=AsyncSession, expire_on_commit=False)
    assert "has_writes" not in plain().sync_session.info  # nothing wired it
    with tenant_scope("default"):
        async with plain() as db:
            got = await contract.admit(
                db,
                tenant_id="default",
                event_id=event_id,
                occurrence_key=key,
                provider=PROVIDER_ID,
                target=KNOWN_TARGET,
                holder="plain-holder",
                now=NOW,
            )
            assert got.admitted
            await finalize_session(db)
    counters, holders = await final(db_state)
    assert holders == ["plain-holder"] and sum(counters.values()) == 1
    with tenant_scope("default"):
        async with plain() as db:
            await contract.release(
                db, tenant_id="default", provider=PROVIDER_ID, holders=["plain-holder"]
            )
            await finalize_session(db)
    counters, holders = await final(db_state)
    assert holders == [] and sum(counters.values()) == 0
