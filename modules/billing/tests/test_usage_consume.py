"""``consume`` / ``record`` / ``check`` against the database."""

from __future__ import annotations

import pytest
from sm_billing.constants import USAGE_STATE_ATTR
from sm_billing.contracts.metering import Allowed, Exceeded, UsageMeter
from sm_billing.metering import sql
from sm_billing.metering.service import UsageService
from usage_helpers import METER, OCT, Clock, events, seed_limits, service, used


@pytest.fixture
def factory(app):
    return app.state.sm.db.session_factory


@pytest.fixture
def usage(app):
    return service(app, Clock())


def test_startup_installs_the_meter(app):
    meter = getattr(app.state, USAGE_STATE_ATTR)
    assert isinstance(meter, UsageService)
    assert isinstance(meter, UsageMeter)


def test_an_unsupported_database_fails_at_startup():
    with pytest.raises(NotImplementedError, match="mysql"):
        sql.ensure_supported("mysql")


async def test_within_and_at_the_limit(factory, usage):
    tenant = await seed_limits(factory, {METER: 3})
    first = await usage.consume(tenant, METER, 1, "k1", source="test")
    assert first == Allowed(used=1, limit=3, period_end=OCT[1])
    assert (await usage.consume(tenant, METER, 2, "k2", source="test")).used == 3
    refused = await usage.consume(tenant, METER, 1, "k3", source="test")
    assert refused == Exceeded(used=3, limit=3, requested=1, period_end=OCT[1])
    assert first.ok and not refused.ok
    assert await used(factory, tenant, OCT[0]) == 3
    # A refused attempt writes nothing.
    assert await events(factory, tenant) == 2


async def test_more_than_the_limit_at_once_writes_nothing(factory, usage):
    tenant = await seed_limits(factory, {METER: 3})
    outcome = await usage.consume(tenant, METER, 4, "big", source="test")
    assert outcome == Exceeded(used=0, limit=3, requested=4, period_end=OCT[1])
    assert await used(factory, tenant, OCT[0]) is None
    assert await events(factory, tenant) == 0


async def test_an_absent_key_is_unlimited_and_still_counted(factory, usage):
    tenant = await seed_limits(factory, {"other": 1})
    for i in range(3):
        outcome = await usage.consume(tenant, METER, 10, f"k{i}", source="test")
        assert isinstance(outcome, Allowed) and outcome.limit is None
    assert await used(factory, tenant, OCT[0]) == 30


async def test_zero_forbids(factory, usage):
    tenant = await seed_limits(factory, {METER: 0})
    outcome = await usage.consume(tenant, METER, 1, "k", source="test")
    assert outcome == Exceeded(used=0, limit=0, requested=1, period_end=OCT[1])


async def test_the_default_plan_applies_without_a_subscription(app, factory, usage):
    # The seeded free plan sets no limits: unlimited.
    outcome = await usage.consume("f" * 32, METER, 1, "k", source="test")
    assert outcome == Allowed(used=1, limit=None, period_end=OCT[1])


async def test_check_is_read_only(factory, usage):
    tenant = await seed_limits(factory, {METER: 2})
    assert await usage.check(tenant, METER, 2) == Allowed(0, 2, OCT[1])
    assert await usage.check(tenant, METER, 3) == Exceeded(0, 2, 3, OCT[1])
    assert await events(factory, tenant) == 0


async def test_record_may_pass_the_limit_and_then_consume_refuses(factory, usage):
    tenant = await seed_limits(factory, {METER: 3})
    recorded = await usage.record(tenant, METER, 5, "job-1", source="worker")
    assert recorded == Allowed(used=5, limit=3, period_end=OCT[1])
    assert isinstance(await usage.consume(tenant, METER, 1, "k", source="test"), Exceeded)


async def test_tenants_are_counted_apart(factory, usage):
    a = await seed_limits(factory, {METER: 1})
    b = await seed_limits(factory, {METER: 1})
    assert isinstance(await usage.consume(a, METER, 1, "same", source="test"), Allowed)
    # Same key, other tenant: its own counter and its own key space.
    assert (await usage.consume(b, METER, 1, "same", source="test")).replayed is False
    assert await used(factory, a, OCT[0]) == 1
    assert await used(factory, b, OCT[0]) == 1


@pytest.mark.parametrize(
    ("qty", "key"),
    [(0, "k"), (-1, "k"), (True, "k"), (1, ""), (1, "x:refund"), (1, "adjust:x"), (1, "k" * 122)],
)
async def test_bad_arguments_raise(factory, usage, qty, key):
    tenant = await seed_limits(factory, {METER: 3})
    with pytest.raises(ValueError):
        await usage.consume(tenant, METER, qty, key, source="test")
