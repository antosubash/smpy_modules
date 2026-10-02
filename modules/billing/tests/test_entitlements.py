from __future__ import annotations

from datetime import UTC, datetime

import pytest
from helpers import make_plan, make_sub, make_tenant
from sm_billing.constants import SubscriptionStatus
from sm_billing.entitlements import PlanEntitlements
from sm_billing.plans import PlanService
from sm_billing.resolve import effective_plan


async def test_no_subscription_resolves_default(app):
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        plan, sub = await effective_plan(session, tenant.id)
        assert plan.is_default
        assert sub is None


@pytest.mark.parametrize(
    ("status", "entitled"),
    [
        (SubscriptionStatus.TRIALING, True),
        (SubscriptionStatus.ACTIVE, True),
        (SubscriptionStatus.PAST_DUE, True),
        (SubscriptionStatus.UNPAID, False),
        (SubscriptionStatus.CANCELED, False),
        (SubscriptionStatus.INCOMPLETE, False),
    ],
)
async def test_status_decides_plan(app, status, entitled):
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        team = await make_plan(session)
        await make_sub(session, tenant, team, status=status)
        plan, sub = await effective_plan(session, tenant.id)
        assert sub is not None
        assert (plan.id == team.id) is entitled
        if not entitled:
            assert plan.is_default


async def test_archived_plan_still_resolves(app):
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        team = await make_plan(session)
        await make_sub(session, tenant, team)
        await PlanService(session).archive(team.id)
        plan, _ = await effective_plan(session, tenant.id)
        assert plan.id == team.id


async def _entitlements_for(app, **plan_kw):
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        team = await make_plan(session, **plan_kw)
        await make_sub(session, tenant, team)
        await session.commit()
        return tenant.id


async def test_limit_absent_key_is_unlimited(app):
    tenant_id = await _entitlements_for(app, limits={"tenants.seats": 3})
    ent = PlanEntitlements(app.state.sm.db.session_factory)
    assert await ent.limit(tenant_id, "tenants.seats") == 3
    assert await ent.limit(tenant_id, "storage.gb") is None


async def test_limit_zero_forbids(app):
    tenant_id = await _entitlements_for(app, limits={"exports": 0})
    ent = PlanEntitlements(app.state.sm.db.session_factory)
    assert await ent.limit(tenant_id, "exports") == 0


async def test_has_feature(app):
    tenant_id = await _entitlements_for(app, features=["sso"])
    ent = PlanEntitlements(app.state.sm.db.session_factory)
    assert await ent.has_feature(tenant_id, "sso") is True
    assert await ent.has_feature(tenant_id, "audit") is False


async def test_startup_installs_plan_entitlements(app):
    assert isinstance(app.state.tenants.entitlements, PlanEntitlements)


async def test_seat_limit_from_plan_blocks_invites(app, user_client):
    """The seam end to end: tenants' own invite endpoint answers 402 at the plan's seats."""
    async with app.state.sm.db.session_factory() as session:
        default = await PlanService(session).default()
        default.limits = {"tenants.seats": 2}
        default.updated_at = datetime.now(UTC)
        await session.commit()
    async with user_client("owner@x.io") as (owner, _):
        created = await owner.post("/api/tenants/", json={"name": "Acme"})
        assert created.status_code == 201, created.text
        ok = await owner.post("/api/tenants/current/invitations", json={"email": "a@x.io"})
        assert ok.status_code == 201, ok.text
        full = await owner.post("/api/tenants/current/invitations", json={"email": "b@x.io"})
        assert full.status_code == 402
        assert full.json()["key"] == "tenants.seats"
