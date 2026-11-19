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
from tests.registration.test_seats_pg import final, seeded, try_admit
from tests.support.providers import PROVIDER_ID

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
