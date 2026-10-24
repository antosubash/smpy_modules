"""A replayed idempotency key is never counted twice; refunds reverse once."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_billing.contracts.metering import Allowed, Exceeded
from sm_billing.metering.validate import ADJUST, REFUND
from sm_billing.models import Plan, Subscription
from sqlalchemy import select
from usage_helpers import METER, NOV, OCT, Clock, events, seed_limits, service, used


@pytest.fixture
def factory(app):
    return app.state.sm.db.session_factory


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def usage(app, clock):
    return service(app, clock)


async def test_the_same_key_counts_once(factory, usage):
    tenant = await seed_limits(factory, {METER: 5})
    first = await usage.consume(tenant, METER, 2, "req-1", source="test")
    again = await usage.consume(tenant, METER, 2, "req-1", source="test")
    assert first == Allowed(2, 5, OCT[1])
    assert again == Allowed(2, 5, OCT[1], replayed=True)
    assert await used(factory, tenant, OCT[0]) == 2
    assert await events(factory, tenant) == 1


async def test_a_replay_after_rollover_counts_in_the_original_period(factory, usage, clock):
    tenant = await seed_limits(factory, {METER: 5})
    await usage.consume(tenant, METER, 1, "req-1", source="test")
    clock.now = datetime(2026, 11, 2, tzinfo=UTC)
    again = await usage.consume(tenant, METER, 1, "req-1", source="test")
    assert again == Allowed(1, 5, OCT[1], replayed=True)
    assert await used(factory, tenant, OCT[0]) == 1
    assert await used(factory, tenant, NOV[0]) is None


async def test_a_replay_still_replays_once_the_limit_is_below_its_qty(factory, usage):
    tenant = await seed_limits(factory, {METER: 5})
    await usage.consume(tenant, METER, 4, "req-1", source="test")
    async with factory() as session:
        sub = (
            await session.execute(select(Subscription).where(Subscription.tenant_id == tenant))
        ).scalar_one()
        (await session.get(Plan, sub.plan_id)).limits = {METER: 2}
        await session.commit()
    again = await usage.consume(tenant, METER, 4, "req-1", source="test")
    assert again == Allowed(4, 2, OCT[1], replayed=True)


async def test_refund_reverses_the_original_period_once(factory, usage, clock):
    tenant = await seed_limits(factory, {METER: 5})
    await usage.consume(tenant, METER, 3, "req-1", source="test")
    clock.now = datetime(2026, 11, 2, tzinfo=UTC)
    await usage.consume(tenant, METER, 1, "req-2", source="test")

    assert await usage.refund(tenant, METER, "req-1") is True
    assert await usage.refund(tenant, METER, "req-1") is False
    assert await used(factory, tenant, OCT[0]) == 0
    assert await used(factory, tenant, NOV[0]) == 1
    assert await events(factory, tenant, kind=REFUND) == 1


async def test_refund_of_an_unknown_key_is_a_no_op(factory, usage):
    tenant = await seed_limits(factory, {METER: 5})
    assert await usage.refund(tenant, METER, "never") is False
    assert await events(factory, tenant) == 0


async def test_a_refused_key_retried_after_an_adjust_succeeds(factory, usage):
    tenant = await seed_limits(factory, {METER: 1})
    await usage.consume(tenant, METER, 1, "req-1", source="test")
    assert isinstance(await usage.consume(tenant, METER, 1, "req-2", source="test"), Exceeded)

    assert await usage.adjust(tenant, METER, -1, reason="goodwill", actor="admin-1") == 0
    retried = await usage.consume(tenant, METER, 1, "req-2", source="test")
    assert retried == Allowed(1, 1, OCT[1])
    assert await events(factory, tenant, kind=ADJUST) == 1


async def test_a_refunded_call_frees_its_capacity(factory, usage):
    tenant = await seed_limits(factory, {METER: 1})
    await usage.consume(tenant, METER, 1, "req-1", source="test")
    await usage.refund(tenant, METER, "req-1")
    assert isinstance(await usage.consume(tenant, METER, 1, "req-2", source="test"), Allowed)


@pytest.mark.parametrize(("quantity", "reason"), [(0, "x"), (1, ""), (1, "   ")])
async def test_adjust_needs_a_quantity_and_a_reason(factory, usage, quantity, reason):
    tenant = await seed_limits(factory, {METER: 1})
    with pytest.raises(ValueError):
        await usage.adjust(tenant, METER, quantity, reason=reason)
