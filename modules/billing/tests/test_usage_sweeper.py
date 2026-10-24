"""The hold sweeper: expiry, the daily ledger purge, and the loop's lifecycle."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sm_billing.constants import PACKAGE, USAGE_STATE_ATTR
from sm_billing.metering import sweeper
from sm_billing.metering.sweeper import UsageSweeper, expire_due, purge
from usage_helpers import GAUGE, METER, Clock, events, gauge_service, hold_statuses, in_use
from usage_helpers import seed_limits as seed


@pytest.fixture
def factory(app):
    return app.state.sm.db.session_factory


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def usage(factory, clock):
    return gauge_service(factory, clock)


async def test_expire_due_returns_capacity_of_lapsed_holds_only(factory, usage, clock):
    tenant = await seed(factory, {GAUGE: 5})
    short = await usage.reserve(tenant, GAUGE, 1, "short", source="t", ttl=60)
    await usage.reserve(tenant, GAUGE, 2, "long", source="t", ttl=600)
    kept = await usage.reserve(tenant, GAUGE, 1, "kept", source="t", ttl=60)
    await usage.commit(kept.id)
    clock.now += timedelta(seconds=61)
    assert await expire_due(usage) == 1
    assert await expire_due(usage) == 0
    assert await in_use(factory, tenant) == 3
    assert await hold_statuses(factory, tenant) == ["committed", "expired", "held"]
    assert await usage.release(short.id) is False


async def test_expire_due_works_in_batches(factory, usage, clock):
    tenant = await seed(factory, {})
    for i in range(5):
        await usage.reserve(tenant, GAUGE, 1, f"k{i}", source="t", ttl=30)
    clock.now += timedelta(seconds=31)
    assert await expire_due(usage, limit=3) == 3
    assert await expire_due(usage, limit=3) == 2
    assert await in_use(factory, tenant) == 0


async def test_an_extended_hold_is_not_expired(factory, usage, clock):
    tenant = await seed(factory, {GAUGE: 1})
    hold = await usage.reserve(tenant, GAUGE, 1, "beat", source="t", ttl=60)
    clock.now += timedelta(seconds=59)
    await usage.extend(hold.id, 60)
    clock.now += timedelta(seconds=30)
    assert await expire_due(usage) == 0
    assert await usage.expire(hold.id) is False  # not lapsed: the guard says no


async def test_purge_drops_old_ledger_rows_and_settled_holds(factory, usage, clock):
    tenant = await seed(factory, {})
    await usage.consume(tenant, METER, 1, "old", source="t")
    old = await usage.reserve(tenant, GAUGE, 1, "old", source="t")
    await usage.release(old.id)
    await usage.reserve(tenant, GAUGE, 1, "live", source="t")
    clock.now += timedelta(days=31)
    await usage.consume(tenant, METER, 1, "new", source="t")
    assert await purge(usage, retention_days=400) == (0, 1)
    assert await hold_statuses(factory, tenant) == ["held"]  # live holds stay
    clock.now += timedelta(days=380)
    assert await purge(usage, retention_days=0) == (0, 0)  # 0 keeps the ledger
    assert await purge(usage, retention_days=400) == (1, 0)
    assert await events(factory, tenant) == 1


async def test_tick_purges_once_a_day(app, factory, clock, monkeypatch):
    usage = gauge_service(factory, clock)
    monkeypatch.setattr(app.state, USAGE_STATE_ATTR, usage)
    calls: list[int] = []

    async def counting(_usage, days):
        calls.append(days)
        return 0, 0

    monkeypatch.setattr(sweeper, "purge", counting)
    sweep = UsageSweeper()
    await sweep.tick(app)
    await sweep.tick(app)
    clock.now += timedelta(days=1)
    await sweep.tick(app)
    assert calls == [400, 400]


async def test_the_loop_runs_on_its_interval_and_idles_at_zero(app, monkeypatch):
    settings = getattr(app.state, PACKAGE).settings
    ticks: list[int] = []

    async def tick(self, _app):
        ticks.append(1)
        return sweeper.SweepReport(expired=1)

    real_sleep = asyncio.sleep
    monkeypatch.setattr(UsageSweeper, "tick", tick)
    monkeypatch.setattr(sweeper, "_sleep", lambda _s: real_sleep(0.01))
    monkeypatch.setattr(settings, "usage_sweep_interval_seconds", 0)
    loop = UsageSweeper()
    loop.start(app)
    await real_sleep(0.1)
    assert ticks == [] and loop.running
    monkeypatch.setattr(settings, "usage_sweep_interval_seconds", 1)
    await real_sleep(0.1)
    assert ticks
    await loop.stop()
    assert not loop.running


async def test_startup_starts_the_sweeper_and_shutdown_stops_it(app):
    services = getattr(app.state, PACKAGE)
    running = services.usage_sweeper
    assert running is not None and running.running
    from sm_billing import startup

    await startup.stop_usage_sweeper(app)
    assert services.usage_sweeper is None and not running.running
