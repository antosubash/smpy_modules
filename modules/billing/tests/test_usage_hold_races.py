"""The gauge acceptance tests: concurrent holds never over-admit or double-release.

Same set-up as ``test_usage_concurrency``: SQLite on a **file** database
(WAL, ``busy_timeout``) through **two engines**, and Postgres
(``SM_TEST_DATABASE_URL``) through the suite's ``NullPool`` engine plus a
second one, so every call has its own connection and the races are real.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from simple_module_db import init_db
from simple_module_test.database import database_is_postgres, database_url_for_tests
from sm_billing.contracts.metering import Closed, Exceeded, Hold
from sm_billing.metering import dbtime
from sm_billing.metering.service import UsageService
from sm_billing.metering.sweeper import expire_due
from sm_billing.models import Base
from sqlalchemy.pool import NullPool
from usage_helpers import FAR, GAUGE, Clock, gauge_service, hold_statuses, in_use, seed_limits

ROUNDS = 20
postgres_only = pytest.mark.skipif(not database_is_postgres(), reason="SM_TEST_DATABASE_URL")


class Race:
    def __init__(self, factories) -> None:
        self.factory = factories[0]
        self.clock = Clock()
        self.meters = [gauge_service(f, self.clock) for f in factories]

    def pick(self, i: int) -> UsageService:
        return self.meters[i % len(self.meters)]


@pytest.fixture
async def sqlite_race(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'race.db'}"
    states = [init_db(url), init_db(url)]
    async with states[0].engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield Race([s.session_factory for s in states])
    for state in states:
        await state.engine.dispose()


@pytest.fixture
async def pg_race(app):
    other = init_db(database_url_for_tests(), poolclass=NullPool)
    yield Race([app.state.sm.db.session_factory, other.session_factory])
    await other.engine.dispose()


async def _two_reserves_admit_one(race: Race) -> None:
    """The issue's acceptance case: ``reserve(t, "jobs.concurrent", 1)`` twice, limit 1."""
    for round_ in range(ROUNDS):
        tenant = await seed_limits(race.factory, {GAUGE: 1})
        outcomes = await asyncio.gather(
            *(race.pick(i).reserve(tenant, GAUGE, 1, f"r{round_}-{i}", source="t") for i in (0, 1))
        )
        assert sum(isinstance(o, Hold) for o in outcomes) == 1, outcomes
        assert sum(isinstance(o, Exceeded) for o in outcomes) == 1
        assert await in_use(race.factory, tenant) == 1
        assert await hold_statuses(race.factory, tenant) == ["held"]


async def _many_reserves_fill_exactly(race: Race) -> None:
    tenant = await seed_limits(race.factory, {GAUGE: 3})
    outcomes = await asyncio.gather(
        *(race.pick(i).reserve(tenant, GAUGE, 1, f"m{i}", source="t") for i in range(10))
    )
    assert sum(isinstance(o, Hold) for o in outcomes) == 3
    assert await in_use(race.factory, tenant) == 3


async def _sweepers_expire_once(race: Race) -> None:
    tenant = await seed_limits(race.factory, {GAUGE: 20})
    for i in range(12):
        await race.pick(i).reserve(tenant, GAUGE, 1, f"s{i}", source="t", ttl=60)
    race.clock.now += timedelta(seconds=61)
    counts = await asyncio.gather(*(expire_due(m) for m in race.meters))
    assert sum(counts) == 12
    assert await in_use(race.factory, tenant) == 0
    assert await hold_statuses(race.factory, tenant) == ["expired"] * 12


async def _release_and_commit_are_idempotent(race: Race) -> None:
    tenant = await seed_limits(race.factory, {GAUGE: 5})
    hold = await race.pick(0).reserve(tenant, GAUGE, 2, "job", source="t")
    committed = await asyncio.gather(*(race.pick(i).commit(hold.id) for i in range(6)))
    assert {c.status for c in committed} == {"committed"}
    assert await in_use(race.factory, tenant) == 2
    released = await asyncio.gather(*(race.pick(i).release(hold.id) for i in range(6)))
    assert released.count(True) == 1
    assert await in_use(race.factory, tenant) == 0


async def _release_races_the_sweeper(race: Race) -> None:
    tenant = await seed_limits(race.factory, {GAUGE: 5})
    holds = [
        await race.pick(0).reserve(tenant, GAUGE, 1, f"x{i}", source="t", ttl=60) for i in range(5)
    ]
    race.clock.now += timedelta(seconds=61)
    results = await asyncio.gather(
        expire_due(race.pick(0)), *(race.pick(1).release(h.id) for h in holds)
    )
    assert results[0] + sum(results[1:]) == 5  # every hold settled by exactly one
    assert await in_use(race.factory, tenant) == 0


async def _two_swaps_of_one_old_hold_free_it_once(race: Race) -> None:
    """Two swaps of the same old hold: only one frees it. At the limit, the
    other needs its whole quantity and is refused; without one, both commit
    and the old hold's quantity comes back exactly once."""
    for round_ in range(ROUNDS // 2):
        tenant = await seed_limits(race.factory, {GAUGE: 10})
        old = await race.pick(0).swap(
            tenant, GAUGE, None, 6, f"o{round_}", source="t", not_after=FAR
        )
        outcomes = await asyncio.gather(
            *(
                race.pick(i).swap(
                    tenant, GAUGE, old.id, 9, f"w{round_}-{i}", source="t", not_after=FAR
                )
                for i in (0, 1)
            )
        )
        assert sum(isinstance(o, Hold) for o in outcomes) == 1, outcomes
        assert await in_use(race.factory, tenant) == 9
        assert await hold_statuses(race.factory, tenant) == ["committed", "refused", "released"]
    free = await seed_limits(race.factory, {})
    old = await race.pick(0).swap(free, GAUGE, None, 6, "o", source="t", not_after=FAR)
    both = await asyncio.gather(
        *(
            race.pick(i).swap(free, GAUGE, old.id, 4, f"u{i}", source="t", not_after=FAR)
            for i in (0, 1)
        )
    )
    assert all(isinstance(o, Hold) for o in both)
    assert await in_use(race.factory, free) == 8  # 6 freed once, 4 + 4 held


class _Paused:
    """Holds the first ``dbtime.now`` - a swap's, taken right after it claimed
    its key, inside its open transaction - until ``go`` is set."""

    def __init__(self) -> None:
        self.real, self.reached, self.go = dbtime.now, asyncio.Event(), asyncio.Event()

    async def __call__(self, session):
        if not self.reached.is_set():
            self.reached.set()
            await self.go.wait()
        return await self.real(session)


async def _close_waits_for_an_in_flight_swap(race: Race) -> None:
    """The swap claimed the key and has not committed: ``close_key`` waits on
    the key's row and returns the swap's hold - it never closes under it."""
    tenant = await seed_limits(race.factory, {GAUGE: 10})
    old = await race.pick(0).swap(tenant, GAUGE, None, 4, "seed", source="t", not_after=FAR)
    pause = _Paused()
    dbtime.now = pause
    try:
        swap = asyncio.create_task(
            race.pick(0).swap(tenant, GAUGE, old.id, 6, "k", source="t", not_after=FAR)
        )
        await asyncio.wait_for(pause.reached.wait(), 10)
        close = asyncio.create_task(race.pick(1).close_key(tenant, GAUGE, "k"))
        await asyncio.sleep(0.3)
        assert not close.done()  # waiting on the swap's claim
        pause.go.set()
        hold, closed = await swap, await close
    finally:
        dbtime.now = pause.real
    assert isinstance(hold, Hold) and isinstance(closed, Hold) and closed.id == hold.id
    assert await in_use(race.factory, tenant) == 6
    assert await hold_statuses(race.factory, tenant) == ["committed", "released"]


async def _a_swap_after_close_writes_nothing(race: Race) -> None:
    """``close_key`` committed first: the swap under the key answers ``Closed``."""
    tenant = await seed_limits(race.factory, {GAUGE: 10})
    old = await race.pick(0).swap(tenant, GAUGE, None, 4, "seed", source="t", not_after=FAR)
    closes = await asyncio.gather(*(race.pick(i).close_key(tenant, GAUGE, "k") for i in (0, 1)))
    assert closes == [Closed("k"), Closed("k")]
    late = await race.pick(1).swap(tenant, GAUGE, old.id, 6, "k", source="t", not_after=FAR)
    assert late == Closed("k")
    assert await in_use(race.factory, tenant) == 4
    assert await hold_statuses(race.factory, tenant) == ["closed", "committed"]


CASES = [
    _two_reserves_admit_one,
    _many_reserves_fill_exactly,
    _sweepers_expire_once,
    _release_and_commit_are_idempotent,
    _release_races_the_sweeper,
    _two_swaps_of_one_old_hold_free_it_once,
    _close_waits_for_an_in_flight_swap,
    _a_swap_after_close_writes_nothing,
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.__name__.strip("_"))
async def test_sqlite(sqlite_race, case):
    await case(sqlite_race)


@postgres_only
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.__name__.strip("_"))
async def test_postgres(pg_race, case):
    await case(pg_race)
