from __future__ import annotations

import pytest
from sm_billing.constants import PricingModel, SubscriptionStatus
from sm_billing.models import Customer, Plan, Subscription, WebhookEvent
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from tenants.models import Tenant


async def _tenant(session, slug: str = "acme") -> Tenant:
    tenant = Tenant(slug=slug, name=slug.title())
    session.add(tenant)
    await session.flush()
    return tenant


async def test_plan_round_trips_json_columns(app):
    async with app.state.sm.db.session_factory() as session:
        plan = Plan(
            key="team",
            name="Team",
            pricing_model=PricingModel.PER_SEAT,
            currency="eur",
            stripe_price_month="price_m",
            limits={"tenants.seats": 10},
            features=["exports"],
        )
        session.add(plan)
        await session.commit()
        loaded = (await session.execute(select(Plan).where(Plan.key == "team"))).scalar_one()
        assert loaded.limits == {"tenants.seats": 10}
        assert loaded.features == ["exports"]
        assert loaded.trial_days == 0
        assert loaded.is_default is False


async def test_one_subscription_per_tenant(app):
    async with app.state.sm.db.session_factory() as session:
        tenant = await _tenant(session)
        plan = Plan(key="p", name="P", pricing_model=PricingModel.FREE, currency="eur")
        session.add(plan)
        await session.flush()
        session.add(Subscription(tenant_id=tenant.id, plan_id=plan.id))
        await session.flush()
        session.add(Subscription(tenant_id=tenant.id, plan_id=plan.id))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_subscription_defaults(app):
    async with app.state.sm.db.session_factory() as session:
        tenant = await _tenant(session)
        plan = Plan(key="p", name="P", pricing_model=PricingModel.FREE, currency="eur")
        session.add(plan)
        await session.flush()
        sub = Subscription(tenant_id=tenant.id, plan_id=plan.id)
        session.add(sub)
        session.add(Customer(tenant_id=tenant.id, provider="manual"))
        session.add(WebhookEvent(id="evt_1", provider="stripe", type="x"))
        await session.commit()
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.quantity == 1
        assert sub.suspended_by_billing is False
        assert sub.cancel_at_period_end is False
