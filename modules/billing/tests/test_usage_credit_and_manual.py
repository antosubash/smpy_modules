"""Two edges of enforcement: a credited counter, and a manual reassignment.

- ``check`` and ``consume`` agree when an admin credit took ``used`` below
  zero and the call is bigger than the limit itself.
- A tenant moved from Stripe to a manual assignment mid-period resets on the
  calendar month, not on the Stripe renewal it no longer has.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from helpers import make_plan, make_sub, make_tenant
from simple_module_db import finalize_session
from sm_billing.admin import assign
from sm_billing.contracts.metering import Allowed, Exceeded
from sm_billing.models import Subscription
from sm_billing.schemas import AssignIn
from sqlalchemy import select
from usage_helpers import METER, NOV, OCT, Clock, events, seed_limits, service, used

STRIPE = (datetime(2026, 10, 7, 9, tzinfo=UTC), datetime(2026, 11, 7, 9, tzinfo=UTC))


@pytest.fixture
def factory(app):
    return app.state.sm.db.session_factory


async def test_a_credit_funds_a_call_bigger_than_the_limit(app, factory):
    usage = service(app, Clock())
    tenant = await seed_limits(factory, {METER: 3})
    assert await usage.adjust(tenant, METER, -5, reason="credit") == -5

    assert await usage.check(tenant, METER, 4) == Allowed(-5, 3, OCT[1])
    assert await usage.consume(tenant, METER, 4, "big", source="t") == Allowed(-1, 3, OCT[1])
    # -1 + 5 = 4 passes the limit: both answer no, and nothing is written.
    assert await usage.check(tenant, METER, 5) == Exceeded(-1, 3, 5, OCT[1])
    assert await usage.consume(tenant, METER, 5, "bigger", source="t") == Exceeded(-1, 3, 5, OCT[1])
    assert await used(factory, tenant, OCT[0]) == -1
    assert await events(factory, tenant) == 2  # the adjust and "big"


@pytest.mark.parametrize("qty", [1, 3, 4, 8])
async def test_check_and_consume_agree(app, factory, qty):
    usage = service(app, Clock())
    tenant = await seed_limits(factory, {METER: 3})
    await usage.adjust(tenant, METER, -2, reason="credit")
    advice = await usage.check(tenant, METER, qty)
    outcome = await usage.consume(tenant, METER, qty, f"k{qty}", source="t")
    assert advice.ok is outcome.ok


async def test_more_than_the_limit_on_a_fresh_period_is_refused(app, factory):
    usage = service(app, Clock())
    tenant = await seed_limits(factory, {METER: 3})
    assert await usage.check(tenant, METER, 4) == Exceeded(0, 3, 4, OCT[1])
    assert await usage.consume(tenant, METER, 4, "k", source="t") == Exceeded(0, 3, 4, OCT[1])
    assert await used(factory, tenant, OCT[0]) is None


async def test_manual_assignment_drops_the_stripe_period(app, factory):
    async with factory() as session:
        tenant = await make_tenant(session, "acme")
        team = await make_plan(session, "team", limits={METER: 5})
        await make_sub(
            session,
            tenant,
            team,
            provider_subscription_id="sub_1",
            trial_end=STRIPE[0],
            current_period_start=STRIPE[0],
            current_period_end=STRIPE[1],
        )
        await finalize_session(session)
        tenant_id, team_id = tenant.id, team.id

    clock = Clock(datetime(2026, 10, 20, tzinfo=UTC))
    usage = service(app, clock)
    assert (await usage.consume(tenant_id, METER, 1, "a", source="t")).period_end == STRIPE[1]

    async with factory() as session:
        await assign(session, app, tenant_id, AssignIn(plan_id=team_id))
        await finalize_session(session)
    async with factory() as session:
        stmt = select(Subscription).where(Subscription.tenant_id == tenant_id)
        sub = (await session.execute(stmt)).scalar_one()
    assert (sub.current_period_start, sub.current_period_end, sub.trial_end) == (None,) * 3

    # Now on the calendar month: 1 November resets it, not the 7th.
    clock.now = datetime(2026, 10, 25, tzinfo=UTC)
    assert await usage.consume(tenant_id, METER, 1, "b", source="t") == Allowed(1, 5, OCT[1])
    clock.now = datetime(2026, 11, 2, tzinfo=UTC)
    assert await usage.consume(tenant_id, METER, 1, "c", source="t") == Allowed(1, 5, NOV[1])
    assert await used(factory, tenant_id, STRIPE[0]) == 1
