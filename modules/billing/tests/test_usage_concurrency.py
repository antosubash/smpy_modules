"""The acceptance tests: concurrent calls never over-admit or double-count.

The suite's default ``:memory:`` + ``StaticPool`` shares one connection and so
cannot race, which is why the SQLite cases run on a **file** database (WAL,
``busy_timeout``) through **two engines**: separate connections, each on its
own aiosqlite thread. The Postgres cases (``SM_TEST_DATABASE_URL``) use the
suite's ``NullPool`` engine plus a second one, so every call has its own
connection and the row lock is real.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from simple_module_db import finalize_session, init_db
from simple_module_test.database import database_is_postgres, database_url_for_tests
from sm_billing.contracts.metering import Allowed, Exceeded
from sm_billing.metering.service import UsageService
from sm_billing.models import Base
from sqlalchemy.pool import NullPool
from usage_helpers import METER, OCT, Clock, events, seed_limits, used

ROUNDS = 5
postgres_only = pytest.mark.skipif(not database_is_postgres(), reason="SM_TEST_DATABASE_URL")


class Race:
    def __init__(self, factories) -> None:
        self.factory = factories[0]
        clock = Clock(datetime(2026, 10, 15, tzinfo=UTC))
        self.meters = [UsageService(f, clock=clock) for f in factories]

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


async def _never_over_admits(race: Race) -> None:
    for round_ in range(ROUNDS):
        tenant = await seed_limits(race.factory, {METER: 3})
        outcomes = await asyncio.gather(
            *(
                race.pick(i).consume(tenant, METER, 1, f"r{round_}-{i}", source="t")
                for i in range(10)
            )
        )
        assert sum(isinstance(o, Allowed) for o in outcomes) == 3
        assert all(o.used == 3 for o in outcomes if isinstance(o, Exceeded))
        assert await used(race.factory, tenant, OCT[0]) == 3
        assert await events(race.factory, tenant) == 3


async def _same_key_counts_once(race: Race) -> None:
    for round_ in range(ROUNDS):
        tenant = await seed_limits(race.factory, {METER: 100})
        outcomes = await asyncio.gather(
            *(race.pick(i).consume(tenant, METER, 1, f"key-{round_}", source="t") for i in range(8))
        )
        assert all(isinstance(o, Allowed) for o in outcomes)
        assert sum(not o.replayed for o in outcomes) == 1
        assert await used(race.factory, tenant, OCT[0]) == 1


async def _refund_races_once(race: Race) -> None:
    tenant = await seed_limits(race.factory, {METER: 5})
    await race.pick(0).consume(tenant, METER, 2, "job", source="t")
    results = await asyncio.gather(*(race.pick(i).refund(tenant, METER, "job") for i in range(6)))
    assert results.count(True) == 1
    assert await used(race.factory, tenant, OCT[0]) == 0


async def _waiter_is_refused_not_admitted(race: Race) -> None:
    """A writer holding the counter makes the next one wait, then refuses it."""
    tenant = await seed_limits(race.factory, {METER: 1})
    first, second = race.meters
    async with race.factory() as caller:
        held = await first.consume(tenant, METER, 1, "slow", source="t", db=caller)
        assert isinstance(held, Allowed)
        waiting = asyncio.create_task(second.consume(tenant, METER, 1, "fast", source="t"))
        await asyncio.sleep(0.5)
        assert not waiting.done(), "the second writer should be blocked on the first"
        await finalize_session(caller)
    assert isinstance(await waiting, Exceeded)
    assert await used(race.factory, tenant, OCT[0]) == 1


async def test_sqlite_concurrent_consumes_never_over_admit(sqlite_race):
    await _never_over_admits(sqlite_race)


async def test_sqlite_concurrent_replays_count_once(sqlite_race):
    await _same_key_counts_once(sqlite_race)


async def test_sqlite_concurrent_refunds_reverse_once(sqlite_race):
    await _refund_races_once(sqlite_race)


async def test_sqlite_waiting_writer_is_refused(sqlite_race):
    await _waiter_is_refused_not_admitted(sqlite_race)


@postgres_only
async def test_postgres_concurrent_consumes_never_over_admit(pg_race):
    await _never_over_admits(pg_race)


@postgres_only
async def test_postgres_concurrent_replays_count_once(pg_race):
    await _same_key_counts_once(pg_race)


@postgres_only
async def test_postgres_concurrent_refunds_reverse_once(pg_race):
    await _refund_races_once(pg_race)


@postgres_only
async def test_postgres_waiting_writer_is_refused(pg_race):
    await _waiter_is_refused_not_admitted(pg_race)
