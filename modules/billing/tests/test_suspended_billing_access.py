"""A billing-suspended owner can still reach the portal — and nobody else can."""

from __future__ import annotations

import pytest
from api_helpers import INERTIA, arm_csrf, create_tenant, page_props
from fake_provider import FakeProvider
from subscription_helpers import _subscribe, _suspend, _team
from tenants.models import Membership
from tenants.resolver import forget


@pytest.fixture
def fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


# ── a billing-suspended owner can still reach the portal ──


async def test_suspended_owner_can_open_portal(app, user_client, fake):
    team = await _team(app)
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await _subscribe(app, tenant["id"], team, status="unpaid", suspended_by_billing=True)
        await _suspend(app, tenant["id"])
        props = await page_props(owner, "/billing/")
        assert props["restore"] is True
        assert props["can_manage"] is False
        assert props["status"]["subscription"]["status"] == "unpaid"
        await arm_csrf(owner)
        response = await owner.post("/api/billing/portal")
        assert response.status_code == 200, response.text
        assert response.json()["url"] == "https://portal.test/session"
        # Nothing but the portal: checkout and plan changes stay closed.
        refused = await owner.post("/api/billing/checkout", json={"plan_id": team})
        assert refused.status_code == 403


async def test_admin_suspended_tenant_is_not_restorable(app, user_client, fake):
    team = await _team(app)
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await _subscribe(app, tenant["id"], team, suspended_by_billing=False)
        await _suspend(app, tenant["id"])
        response = await owner.get("/billing/", headers=INERTIA)
        assert response.status_code == 303


async def test_suspended_tenant_member_cannot_restore(app, user_client, fake):
    team = await _team(app)
    async with user_client("owner@x.io") as (owner, _), user_client("m@x.io") as (member, mid):
        tenant = await create_tenant(owner)
        await _subscribe(app, tenant["id"], team, status="unpaid", suspended_by_billing=True)
        async with app.state.sm.db.session_factory() as session:
            session.add(Membership(tenant_id=tenant["id"], user_id=mid, role="admin"))
            await session.commit()
        forget(None)
        await member.post(f"/api/tenants/{tenant['id']}/switch")
        await _suspend(app, tenant["id"])
        response = await member.get("/billing/", headers=INERTIA)
        assert response.status_code == 303
