"""``release`` never takes a counter lock out of order (Postgres, interleavings forced)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from sm_events.contracts import registration as contract
from sm_events.core.errors_registration import SeatsBusy
from sm_events.core.tenancy import tenant_scope
from sm_events.registration import release as release_module
from sm_events.registration.seats import release_target
from sqlalchemy import text

from tests.pg_support import USING_POSTGRES
from tests.registration import lock_trace
from tests.registration.test_seats_pg import TIMEOUT, final, seeded, try_admit, try_release
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID

pytestmark = pytest.mark.skipif(not USING_POSTGRES, reason="needs real concurrent transactions")
DAY1 = datetime(2026, 7, 1, 8)
ROUNDS = 50


def day(event_id, n: int) -> str:
    return f"{event_id}:{(DAY1 + timedelta(days=n)).strftime('%Y%m%dT%H%M%SZ')}"


async def target_release(state):
    with tenant_scope("default"):
        async with state.session_factory() as db:
            got = await release_target(
                db, tenant_id="default", provider=PROVIDER_ID, target=KNOWN_TARGET
            )
            await db.commit()
            return got


def hook_lock(monkeypatch, action):
    """Run ``action`` after the first counter lock a release holds (not again)."""
    real = release_module.lock_counters
    state = {"calls": 0}

    async def wrapped(db, tenant, keys):
        got = await real(db, tenant, keys)
        state["calls"] += 1
        await action(state["calls"])
        return got

    monkeypatch.setattr(release_module, "lock_counters", wrapped)


async def test_a_savepoint_rollback_releases_row_locks_pg(db_state):
    """Verified, not assumed: a row lock taken after a savepoint is gone once it is rolled back."""
    event_id, key = await seeded(db_state, capacity=5)
    await try_admit(db_state, event_id, key, "h1")
    with tenant_scope("default"):
        async with db_state.session_factory() as one, db_state.session_factory() as two:
            await one.execute(text("SAVEPOINT s"))
            await one.execute(text("SELECT id FROM events_registration_count FOR UPDATE"))
            with pytest.raises(Exception, match="could not obtain lock"):
                await two.execute(
                    text("SELECT id FROM events_registration_count FOR UPDATE NOWAIT")
                )
            await two.rollback()
            await one.execute(text("ROLLBACK TO SAVEPOINT s"))
            await two.execute(text("SELECT id FROM events_registration_count FOR UPDATE NOWAIT"))
            await two.rollback()
            await one.rollback()


async def test_a_lower_occurrence_found_late_restarts_in_order_pg(db_state, monkeypatch):
    event_id, _ = await seeded(db_state, capacity=50, series_event=True, rule="FREQ=DAILY")
    trace = lock_trace.install(monkeypatch)
    for i in range(ROUNDS):
        lo, hi = day(event_id, 2 * i), day(event_id, 2 * i + 1)  # lo's counter is created first
        await try_admit(db_state, event_id, lo, f"a{i}")
        await try_admit(db_state, event_id, hi, f"b{i}")
        await try_release(db_state, f"a{i}")  # lo keeps its counter, with no seat

        async def compete(call, i=i, lo=lo):
            if call == 1:  # a holder lands at the LOWER occurrence while the release holds hi
                assert (await try_admit(db_state, event_id, lo, f"c{i}")).admitted

        hook_lock(monkeypatch, compete)
        await asyncio.wait_for(target_release(db_state), TIMEOUT)
        monkeypatch.setattr(release_module, "lock_counters", release_module.lock_counters)
        counters, holders = await final(db_state)  # recomputed from the rows
        assert holders == [] and set(counters.values()) <= {0}, i
        monkeypatch.undo()
        trace = lock_trace.install(monkeypatch)
    assert trace.by_session is not None


async def test_the_bound_exceeded_is_seats_busy_and_nothing_changes_pg(db_state, monkeypatch):
    event_id, _ = await seeded(db_state, capacity=50, series_event=True, rule="FREQ=DAILY")
    keys = [day(event_id, n) for n in range(9)]
    for n, key in enumerate(keys):  # counters 1..9 in creation order
        await try_admit(db_state, event_id, key, f"s{n}")
    for n in range(8):
        await try_release(db_state, f"s{n}")  # only the highest occurrence still holds a seat
    before = await final(db_state)
    lower = iter(reversed(keys[:8]))

    async def keep_going(call):
        nxt = next(lower, None)
        if nxt is not None:
            assert (await try_admit(db_state, event_id, nxt, f"n{call}")).admitted

    hook_lock(monkeypatch, keep_going)
    with pytest.raises(SeatsBusy) as caught:
        await target_release(db_state)
    assert caught.value.status_code == 409 and caught.value.code == "seats_busy"
    after = await final(db_state)
    new_seats = sum(1 for h in after[1] if h.startswith("n"))
    assert new_seats >= 1 and len(after[1]) == len(before[1]) + new_seats  # nothing was released
    assert contract.SeatsBusy is SeatsBusy
