"""Tenant-facing billing API: status, checkout, portal, change plan."""

from __future__ import annotations

import pytest
from api_helpers import arm_csrf, create_tenant, page_props
from fake_provider import FakeProvider
from helpers import make_plan
from sm_billing.contracts.provider import SubscriptionSnapshot
from sm_billing.models import Customer, Subscription
from sqlalchemy import select
from tenants.models import Membership


@pytest.fixture
def fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


async def _plans(app, **team_kw):
    async with app.state.sm.db.session_factory() as session:
        team = await make_plan(session, "team", **team_kw)
        await session.commit()
        return team.id


async def _subscribe(app, tenant_id: str, plan_id: int, sid: str = "sub_1") -> None:
    async with app.state.sm.db.session_factory() as session:
        session.add(Subscription(tenant_id=tenant_id, plan_id=plan_id, provider_subscription_id=sid))
        session.add(Customer(tenant_id=tenant_id, provider="stripe", provider_customer_id="cus_1"))
        await session.commit()


async def _add_members(app, tenant_id: str, n: int) -> None:
    async with app.state.sm.db.session_factory() as session:
        for i in range(n):
            session.add(Membership(tenant_id=tenant_id, user_id=f"extra-{i}", role="member"))
        await session.commit()


def _snapshot(tenant_id, price, quantity=1, status="active", cancel=False):
    return SubscriptionSnapshot(
        id="sub_1", customer_id="cus_1", tenant_id=tenant_id, status=status, price_id=price,
        quantity=quantity, trial_end=None, current_period_end=None, cancel_at_period_end=cancel,
    )


async def test_billing_page_without_tenant_redirects(user_client):
    async with user_client("lonely@x.io") as (client, _):
        response = await client.get("/billing/")
        assert response.status_code == 303
        assert response.headers["location"] == "/tenants/?reason=tenant_required"


async def test_status_on_default_plan(app, user_client):
    async with user_client("owner@x.io") as (owner, _):
        await create_tenant(owner)
        status = (await owner.get("/api/billing/status")).json()
        assert status["plan"]["key"] == "free"
        assert status["subscription"] is None
        assert status["seats"] == {"used": 1, "limit": None}
        assert status["checkout_available"] is False
        props = await page_props(owner, "/billing/")
        assert props["can_manage"] is True
        assert [p["key"] for p in props["plans"]] == ["free"]


async def test_checkout_unavailable_under_manual(app, user_client):
    team = await _plans(app)
    async with user_client("owner@x.io") as (owner, _):
        await create_tenant(owner)
        await arm_csrf(owner)
        response = await owner.post("/api/billing/checkout", json={"plan_id": team})
        assert response.status_code == 409
        assert response.json()["detail"] == "checkout_unavailable"


async def test_checkout_requires_csrf(app, user_client, fake):
    team = await _plans(app)
    async with user_client("owner@x.io") as (owner, _):
        await create_tenant(owner)
        response = await owner.post("/api/billing/checkout", json={"plan_id": team})
        assert response.status_code == 403


async def test_checkout_creates_customer_once(app, user_client, fake):
    team = await _plans(app, pricing_model="per_seat", trial_days=14)
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await arm_csrf(owner)
        for _ in range(2):
            response = await owner.post(
                "/api/billing/checkout", json={"plan_id": team, "interval": "year"}
            )
            assert response.status_code == 200, response.text
            assert response.json()["url"] == "https://checkout.test/session"
    assert len(fake.called("ensure_customer")) == 1
    call = fake.called("checkout_url")[-1]
    assert call["price_id"] == "price_team_y"
    assert (call["quantity"], call["trial_days"], call["tenant_id"]) == (1, 14, tenant["id"])
    assert call["success_url"].endswith("/billing/?checkout=success")
    async with app.state.sm.db.session_factory() as session:
        assert (await session.get(Customer, tenant["id"])).provider_customer_id == "cus_1"


async def test_checkout_refuses_free_and_archived(app, user_client, fake):
    async with user_client("owner@x.io") as (owner, _):
        await create_tenant(owner)
        await arm_csrf(owner)
        free = (await owner.get("/api/billing/status")).json()["plan"]["id"]
        response = await owner.post("/api/billing/checkout", json={"plan_id": free})
        assert response.json()["detail"] == "plan_is_free"
        response = await owner.post("/api/billing/checkout", json={"plan_id": 9999})
        assert response.status_code == 404


async def test_member_cannot_manage(app, user_client, fake):
    team = await _plans(app)
    async with user_client("owner@x.io") as (owner, _), user_client("m@x.io") as (member, _):
        await create_tenant(owner)
        invite = await owner.post(
            "/api/tenants/current/invitations", json={"email": "m@x.io", "role": "admin"}
        )
        accepted = await member.post(
            "/api/tenants/invitations/accept", json={"token": invite.json()["token"]}
        )
        assert accepted.status_code == 200, accepted.text
        await arm_csrf(member)
        assert (await member.get("/api/billing/status")).status_code == 200
        response = await member.post("/api/billing/checkout", json={"plan_id": team})
        assert response.status_code == 403
        assert (await page_props(member, "/billing/"))["can_manage"] is False


async def test_portal(app, user_client, fake):
    team = await _plans(app)
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await arm_csrf(owner)
        assert (await owner.post("/api/billing/portal")).json()["detail"] == "no_customer"
        await _subscribe(app, tenant["id"], team)
        response = await owner.post("/api/billing/portal")
        assert response.json() == {"url": "https://portal.test/session"}
        assert fake.called("portal_url")[-1]["return_url"].endswith("/billing/")


async def test_change_plan_paid_to_paid(app, user_client, fake):
    team = await _plans(app)
    async with app.state.sm.db.session_factory() as session:
        pro = (await make_plan(session, "pro", pricing_model="per_seat")).id
        await session.commit()
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await _subscribe(app, tenant["id"], team)
        fake.snapshots["sub_1"] = _snapshot(tenant["id"], "price_pro_m")
        await arm_csrf(owner)
        response = await owner.post("/api/billing/change-plan", json={"plan_id": pro})
        assert response.status_code == 200, response.text
        assert response.json()["plan"]["key"] == "pro"
    assert fake.called("change_plan")[-1] == {
        "subscription_id": "sub_1", "price_id": "price_pro_m", "quantity": 1
    }


async def test_change_plan_to_free_cancels_at_period_end(app, user_client, fake):
    team = await _plans(app)
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await _subscribe(app, tenant["id"], team)
        fake.snapshots["sub_1"] = _snapshot(tenant["id"], "price_team_m", cancel=True)
        await arm_csrf(owner)
        free = (await owner.get("/api/billing/status")).json()["plan"]
        assert free["key"] == "team"
        plans = (await page_props(owner, "/billing/"))["plans"]
        free_id = next(p["id"] for p in plans if p["key"] == "free")
        response = await owner.post("/api/billing/change-plan", json={"plan_id": free_id})
        assert response.status_code == 200, response.text
        assert response.json()["subscription"]["cancel_at_period_end"] is True
    assert fake.called("cancel_at_period_end") == [{"subscription_id": "sub_1"}]


async def test_change_plan_seat_guard(app, user_client, fake):
    team = await _plans(app)
    async with app.state.sm.db.session_factory() as session:
        small = (await make_plan(session, "small", limits={"tenants.seats": 2})).id
        await session.commit()
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await _subscribe(app, tenant["id"], team)
        await _add_members(app, tenant["id"], 3)
        await arm_csrf(owner)
        response = await owner.post("/api/billing/change-plan", json={"plan_id": small})
        assert response.status_code == 409
        assert response.json() == {"detail": "too_many_members", "used": 4, "limit": 2}
    assert fake.called("change_plan") == []


async def test_change_plan_without_subscription_points_to_checkout(app, user_client, fake):
    team = await _plans(app)
    async with user_client("owner@x.io") as (owner, _):
        await create_tenant(owner)
        await arm_csrf(owner)
        response = await owner.post("/api/billing/change-plan", json={"plan_id": team})
        assert response.json()["detail"] == "no_subscription"


async def test_provider_error_is_502(app, user_client, fake):
    team = await _plans(app)
    fake.fail.add("checkout_url")
    async with user_client("owner@x.io") as (owner, _):
        await create_tenant(owner)
        await arm_csrf(owner)
        response = await owner.post("/api/billing/checkout", json={"plan_id": team})
        assert response.status_code == 502
        assert response.json()["detail"] == "provider_error"


async def test_status_seats_count_members(app, user_client):
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await _add_members(app, tenant["id"], 2)
        async with app.state.sm.db.session_factory() as session:
            rows = (await session.execute(select(Membership))).scalars().all()
            assert len(rows) == 3
        assert (await owner.get("/api/billing/status")).json()["seats"]["used"] == 3
