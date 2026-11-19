"""``release`` and ``release_target`` against concurrent admits, with the interleaving forced.

The window under test: between reading which occurrences a release touches and deleting the seats,
an admit on *another* occurrence commits. The seat it made must end released with its counter
corrected, or untouched, never deleted with a counter nobody recomputed. A hook on the counter lock
runs the competing admit at exactly that point, in both orders (before the lock is taken and after
it is held), fifty times each. Every test ends by recomputing all counters from the seat rows.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Event
from sm_events.registration import release as release_module
from sm_events.registration.seats import release_target
from sqlalchemy import update

from tests.pg_support import USING_POSTGRES
from tests.registration.support import consistent
from tests.registration.test_seats_pg import (
    TIMEOUT,
    final,
    seeded,
    try_admit,
    try_release,
)
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID

pytestmark = pytest.mark.skipif(not USING_POSTGRES, reason="needs real concurrent transactions")

ROUNDS = 50
DAY1 = datetime(2026, 7, 1, 8)


def day(event_id, n: int) -> str:
    return f"{event_id}:{(DAY1 + timedelta(days=n)).strftime('%Y%m%dT%H%M%SZ')}"


def hook_lock(monkeypatch, *, when: str, action):
    """Run ``action`` once, before or after the first counter lock a release takes."""
    real = release_module.lock_counters
    state = {"calls": 0}

    async def wrapped(db, tenant, keys):
        first = state["calls"] == 0
        state["calls"] += 1
        if first and when == "before":
            await action()
        got = await real(db, tenant, keys)
        if first and when == "after":
            await action()
        return got

    monkeypatch.setattr(release_module, "lock_counters", wrapped)


async def target_release(state):
    with tenant_scope("default"):
        async with state.session_factory() as db:
            got = await release_target(
                db, tenant_id="default", provider=PROVIDER_ID, target=KNOWN_TARGET
            )
            await db.commit()
            return got


@pytest.mark.parametrize("when", ["before", "after"])
async def test_release_target_racing_an_admit_elsewhere_pg(db_state, monkeypatch, when):
    event_id, _ = await seeded(db_state, capacity=50, series_event=True, rule="FREQ=DAILY")
    for i in range(ROUNDS):
        await try_admit(db_state, event_id, day(event_id, 2 * i), f"a{i}")

        async def compete(i=i):
            got = await try_admit(db_state, event_id, day(event_id, 2 * i + 1), f"b{i}")
            assert got.admitted

        hook_lock(monkeypatch, when=when, action=compete)
        await asyncio.wait_for(target_release(db_state), TIMEOUT)
        monkeypatch.undo()
        counters, holders = await final(db_state)  # recomputed from the rows, every round
        assert holders == [] and set(counters.values()) <= {0}, (when, i)


@pytest.mark.parametrize("when", ["before", "after"])
async def test_release_racing_an_admit_elsewhere_pg(db_state, monkeypatch, when):
    event_id, _ = await seeded(db_state, capacity=50, series_event=True, rule="FREQ=DAILY")
    for i in range(ROUNDS):
        await try_admit(db_state, event_id, day(event_id, 2 * i), f"a{i}")

        async def compete(i=i):
            assert (await try_admit(db_state, event_id, day(event_id, 2 * i + 1), f"b{i}")).admitted

        hook_lock(monkeypatch, when=when, action=compete)
        await asyncio.wait_for(try_release(db_state, f"a{i}", f"b{i}"), TIMEOUT)
        monkeypatch.undo()
        counters, holders = await final(db_state)
        assert holders == [] and set(counters.values()) <= {0}, (when, i)


async def test_two_target_releases_and_admits_at_once_pg(db_state):
    event_id, _ = await seeded(db_state, capacity=50, series_event=True, rule="FREQ=DAILY")
    for n in range(10):
        await try_admit(db_state, event_id, day(event_id, n), f"s{n}")
    jobs = [target_release(db_state), target_release(db_state)]
    jobs += [try_admit(db_state, event_id, day(event_id, n % 12), f"x{n}") for n in range(24)]
    await asyncio.wait_for(asyncio.gather(*jobs), TIMEOUT)
    counters, holders = await final(db_state)
    assert sum(counters.values()) == len(holders)


async def test_release_target_racing_a_capacity_decrease_pg(db_state):
    event_id, _ = await seeded(db_state, capacity=50, series_event=True, rule="FREQ=DAILY")
    for n in range(10):
        await try_admit(db_state, event_id, day(event_id, n), f"s{n}")

    async def lower():
        with tenant_scope("default"):
            async with db_state.session_factory() as db:
                await db.execute(
                    update(Event.__table__)  # type: ignore[attr-defined]
                    .where(Event.__table__.c.id == event_id)  # type: ignore[attr-defined]
                    .values(registration_capacity=1)
                )
                await db.commit()

    await asyncio.wait_for(asyncio.gather(target_release(db_state), lower()), TIMEOUT)
    counters, holders = await final(db_state)
    assert holders == [] and set(counters.values()) <= {0}
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            await consistent(db)
