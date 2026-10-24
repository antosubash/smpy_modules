"""Checkout: one trial per organisation, and no second live subscription."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from api_helpers import arm_csrf, create_tenant
from fake_provider import FakeProvider
from simple_module_db import finalize_session
from sm_billing.admin import assign
from sm_billing.constants import PROVIDER_CHECKOUT_BLOCKING_STATUSES
from sm_billing.models import Customer
from sm_billing.resolve import subscription_for
from sm_billing.schemas import AssignIn
from subscription_helpers import _subscribe, _team

TRIAL_END = datetime(2026, 10, 21, tzinfo=UTC)


@pytest.fixture
def fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


# ── one trial per organisation ──


async def test_trial_only_once(app, user_client, fake):
    team = await _team(app, trial_days=14)
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await _subscribe(app, tenant["id"], team, status="canceled")
        await arm_csrf(owner)
        response = await owner.post("/api/billing/checkout", json={"plan_id": team})
        assert response.status_code == 200, response.text
    assert fake.called("create_checkout")[-1]["trial_days"] == 0


async def test_trial_spent_at_stripe_survives_a_manual_assignment(app, user_client):
    # Stripe trial → admin moves the tenant to a manual plan → back to Stripe.
    team = await _team(app, trial_days=14)
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await _subscribe(app, tenant["id"], team, status="active", trial_end=TRIAL_END)
        async with app.state.sm.db.session_factory() as session:
            await assign(session, app, tenant["id"], AssignIn(plan_id=team, status="canceled"))
            await finalize_session(session)
        async with app.state.sm.db.session_factory() as session:
            sub = await subscription_for(session, tenant["id"])
        assert sub.provider_subscription_id is None and sub.current_period_end is None
        assert sub.trial_end is not None

        fake = FakeProvider()
        app.state.sm_billing.provider = fake
        await arm_csrf(owner)
        response = await owner.post("/api/billing/checkout", json={"plan_id": team})
        assert response.status_code == 200, response.text
    assert fake.called("create_checkout")[-1]["trial_days"] == 0


# ── no second live subscription ──


async def test_checkout_refused_when_provider_has_live_subscription(app, user_client, fake):
    team = await _team(app)
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        async with app.state.sm.db.session_factory() as session:
            session.add(
                Customer(tenant_id=tenant["id"], provider="stripe", provider_customer_id="cus_1")
            )
            await session.commit()
        fake.live["cus_1"] = ["sub_elsewhere"]
        await arm_csrf(owner)
        response = await owner.post("/api/billing/checkout", json={"plan_id": team})
        assert (response.status_code, response.json()["detail"]) == (409, "already_subscribed")


async def test_a_failed_first_payment_can_check_out_again(app, user_client, fake):
    """``incomplete`` blocks neither side: change-plan has nothing to change,
    so checkout must stay open (``test_stripe_listing`` covers the filter)."""
    team = await _team(app)
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await _subscribe(app, tenant["id"], team, status="incomplete")
        await arm_csrf(owner)
        response = await owner.post("/api/billing/checkout", json={"plan_id": team})
        assert response.status_code == 200, response.text
    statuses = fake.called("live_subscription_ids")[-1]["statuses"]
    assert statuses == PROVIDER_CHECKOUT_BLOCKING_STATUSES
    assert "incomplete" not in statuses


async def test_new_checkout_expires_the_previous_session(app, user_client, fake):
    team = await _team(app)
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await arm_csrf(owner)
        for _ in range(2):
            ok = await owner.post("/api/billing/checkout", json={"plan_id": team})
            assert ok.status_code == 200, ok.text
    assert fake.called("expire_checkout") == [{"session_id": "cs_1"}]
    async with app.state.sm.db.session_factory() as session:
        assert (await session.get(Customer, tenant["id"])).checkout_session_id == "cs_2"
