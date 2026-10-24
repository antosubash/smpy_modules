"""Gauge holds against the database: reserve, commit, release, extend, holding."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_billing.contracts.metering import (
    Exceeded,
    Hold,
    HoldExpired,
    HoldNotFound,
    IdempotencyConflict,
    QuotaExceededError,
)
from sm_billing.metering.errors import IdempotencyReplay
from sm_billing.metering.registry import MeterRegistry
from usage_helpers import GAUGE, Clock, gauge_service, hold_statuses, in_use, seed_limits


@pytest.fixture
def factory(app):
    return app.state.sm.db.session_factory


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def usage(factory, clock):
    return gauge_service(factory, clock)


async def test_reserve_commit_release(factory, usage, clock):
    tenant = await seed_limits(factory, {GAUGE: 2})
    hold = await usage.reserve(tenant, GAUGE, 1, "job-1", source="t")
    assert isinstance(hold, Hold) and hold.ok and hold.status == "held"
    assert hold.expires_at == clock.now + timedelta(seconds=900)
    assert await in_use(factory, tenant) == 1
    committed = await usage.commit(hold.id)
    assert committed.status == "committed" and committed.expires_at is None
    assert await usage.commit(hold.id) == committed  # idempotent
    assert await usage.release(hold.id) is True
    assert await usage.release(hold.id) is False  # idempotent
    assert await in_use(factory, tenant) == 0
    assert await hold_statuses(factory, tenant) == ["released"]


async def test_the_limit_holds_and_a_release_frees_it(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 2})
    first = await usage.reserve(tenant, GAUGE, 2, "a", source="t")
    refused = await usage.reserve(tenant, GAUGE, 1, "b", source="t")
    assert refused == Exceeded(used=2, limit=2, requested=1, period_end=None)
    assert not refused.ok
    assert await hold_statuses(factory, tenant) == ["held"]  # a refusal writes nothing
    await usage.release(first.id)
    assert isinstance(await usage.reserve(tenant, GAUGE, 1, "b", source="t"), Hold)


async def test_more_than_the_limit_and_zero_forbid(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 2})
    assert isinstance(await usage.reserve(tenant, GAUGE, 3, "big", source="t"), Exceeded)
    assert await in_use(factory, tenant) is None
    forbidden = await seed_limits(factory, {GAUGE: 0})
    assert isinstance(await usage.reserve(forbidden, GAUGE, 1, "x", source="t"), Exceeded)


async def test_an_absent_limit_is_unlimited(factory, usage):
    tenant = await seed_limits(factory, {})
    for i in range(3):
        assert isinstance(await usage.reserve(tenant, GAUGE, 50, f"k{i}", source="t"), Hold)
    assert await in_use(factory, tenant) == 150


async def test_a_replayed_key_holds_once(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 5})
    first = await usage.reserve(tenant, GAUGE, 2, "job", source="t")
    again = await usage.reserve(tenant, GAUGE, 2, "job", source="t")
    assert again.id == first.id and again.replayed and not first.replayed
    assert await in_use(factory, tenant) == 2
    with pytest.raises(IdempotencyConflict):
        await usage.reserve(tenant, GAUGE, 3, "job", source="t")
    with pytest.raises(IdempotencyConflict):
        await usage.reserve(tenant, GAUGE, 2, "job", source="other")
    await usage.release(first.id)
    settled = await usage.reserve(tenant, GAUGE, 2, "job", source="t")
    assert settled.replayed and settled.status == "released" and not settled.ok
    assert await in_use(factory, tenant) == 0


async def test_a_replay_is_answered_before_the_limit(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 1})
    first = await usage.reserve(tenant, GAUGE, 1, "only", source="t")
    assert (await usage.reserve(tenant, GAUGE, 1, "only", source="t")).id == first.id
    with pytest.raises(IdempotencyConflict):
        await usage.reserve(tenant, GAUGE, 5, "only", source="t")  # qty > limit path


async def test_commit_or_extend_after_expiry_raises_and_frees(factory, usage, clock):
    tenant = await seed_limits(factory, {GAUGE: 1})
    hold = await usage.reserve(tenant, GAUGE, 1, "late", source="t", ttl=60)
    clock.now += timedelta(seconds=61)
    with pytest.raises(HoldExpired) as caught:
        await usage.commit(hold.id)
    assert caught.value.status == "expired"
    assert await in_use(factory, tenant) == 0  # the late commit expired it
    with pytest.raises(HoldExpired):
        await usage.extend(hold.id, 60)
    assert await usage.release(hold.id) is False


async def test_extend_pushes_the_expiry(factory, usage, clock):
    tenant = await seed_limits(factory, {GAUGE: 1})
    hold = await usage.reserve(tenant, GAUGE, 1, "long", source="t", ttl=60)
    clock.now += timedelta(seconds=50)
    extended = await usage.extend(hold.id, 120)
    assert extended.expires_at == clock.now + timedelta(seconds=120)
    clock.now += timedelta(seconds=100)
    assert (await usage.commit(hold.id)).status == "committed"
    assert (await usage.extend(hold.id, 60)).expires_at is None  # committed: no expiry


async def test_released_hold_cannot_be_committed(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 1})
    hold = await usage.reserve(tenant, GAUGE, 1, "r", source="t")
    await usage.release(hold.id)
    with pytest.raises(HoldExpired) as caught:
        await usage.commit(hold.id)
    assert caught.value.status == "released"


async def test_unknown_hold_ids(usage):
    for call in (usage.commit, usage.release):
        with pytest.raises(HoldNotFound):
            await call("0" * 32)
    with pytest.raises(HoldNotFound):
        await usage.extend("0" * 32, 60)


async def test_ttl_defaults_meter_then_setting(factory, clock):
    reg = MeterRegistry()
    reg.define(key=GAUGE, kind="gauge", hold_ttl_seconds=30)
    reg.define(key="storage.bytes", kind="gauge", unit="bytes")
    usage = gauge_service(factory, clock, meters=reg, hold_ttl=lambda: 120)
    tenant = await seed_limits(factory, {})
    meter_ttl = await usage.reserve(tenant, GAUGE, 1, "a", source="t")
    setting_ttl = await usage.reserve(tenant, "storage.bytes", 1, "b", source="t")
    explicit = await usage.reserve(tenant, GAUGE, 1, "c", source="t", ttl=45)
    assert meter_ttl.expires_at == clock.now + timedelta(seconds=30)
    assert setting_ttl.expires_at == clock.now + timedelta(seconds=120)
    assert explicit.expires_at == clock.now + timedelta(seconds=45)
    with pytest.raises(ValueError, match="ttl"):
        await usage.reserve(tenant, GAUGE, 1, "d", source="t", ttl=0)


async def test_holding_releases_on_exit_and_on_error(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 1})
    async with usage.holding(tenant, GAUGE, 1, "ok", source="t") as hold:
        assert hold.ok and await in_use(factory, tenant) == 1
    assert await in_use(factory, tenant) == 0
    with pytest.raises(RuntimeError):
        async with usage.holding(tenant, GAUGE, 1, "boom", source="t"):
            raise RuntimeError("job failed")
    assert await in_use(factory, tenant) == 0
    assert await hold_statuses(factory, tenant) == ["released", "released"]


async def test_holding_a_failed_release_never_masks_the_blocks_error(factory, usage, monkeypatch):
    tenant = await seed_limits(factory, {GAUGE: 1})

    async def broken_release(hold_id):
        raise OSError("database is locked")

    monkeypatch.setattr(usage, "release", broken_release)
    with pytest.raises(RuntimeError, match="job failed"):
        async with usage.holding(tenant, GAUGE, 1, "masked", source="t"):
            raise RuntimeError("job failed")
    assert await hold_statuses(factory, tenant) == ["held"]  # the TTL returns it


async def test_holding_refused_raises_quota_exceeded(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 1})
    first = await usage.reserve(tenant, GAUGE, 1, "busy", source="t")
    with pytest.raises(QuotaExceededError) as caught:
        async with usage.holding(tenant, GAUGE, 1, "second", source="t"):
            pytest.fail("must not enter")
    assert caught.value.meter == GAUGE and caught.value.outcome.used == 1
    # A replay of a live key never enters: the block runs once per key.
    with pytest.raises(IdempotencyReplay):
        async with usage.holding(tenant, GAUGE, 1, "busy", source="t"):
            pytest.fail("a replayed key must not enter")
    assert await in_use(factory, tenant) == 1
    assert await hold_statuses(factory, tenant) == ["held"]  # the owner's hold stays
    await usage.release(first.id)
    with pytest.raises(HoldExpired):
        async with usage.holding(tenant, GAUGE, 1, "busy", source="t"):
            pytest.fail("a settled key must not enter")


async def test_recount_repairs_drift(factory, usage):
    from sm_billing.models import UsageGauge
    from sqlalchemy import update

    tenant = await seed_limits(factory, {GAUGE: 10})
    keep = await usage.reserve(tenant, GAUGE, 3, "a", source="t")
    await usage.commit(keep.id)
    gone = await usage.reserve(tenant, GAUGE, 2, "b", source="t")
    await usage.reserve(tenant, GAUGE, 1, "c", source="t")
    await usage.release(gone.id)
    async with factory() as session:
        await session.execute(update(UsageGauge).values(in_use=9))
        await session.commit()
    assert await usage.recount(tenant, GAUGE) == 4
    assert await in_use(factory, tenant) == 4
    fresh = await seed_limits(factory, {})
    assert await usage.recount(fresh, GAUGE) == 0  # creates the row
