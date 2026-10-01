"""Regression tests for the final-review findings (see the plan ledger)."""

from __future__ import annotations

import httpx
import pytest
from api_helpers import INERTIA, arm_csrf, create_tenant, page_props
from fake_provider import GOOD_SIGNATURE, SIGNATURE_HEADER, FakeProvider
from helpers import make_plan, make_tenant
from sm_billing import constants as c
from sm_billing.contracts.provider import SubscriptionSnapshot, WebhookEvent
from sm_billing.models import Customer, Plan, Subscription
from sm_billing.models import WebhookEvent as EventRow
from sm_billing.plans import PlanError, PlanService
from sm_billing.schemas import PlanIn
from sqlalchemy import select
from tenants.constants import TenantStatus
from tenants.models import Membership, Tenant
from tenants.resolver import forget

HEADERS = {SIGNATURE_HEADER: GOOD_SIGNATURE}


@pytest.fixture
def fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


def _snap(tenant_id, *, status="active", price="price_team_m", sid="sub_1", quantity=1):
    return SubscriptionSnapshot(
        id=sid,
        customer_id="cus_1",
        tenant_id=tenant_id,
        status=status,
        price_id=price,
        quantity=quantity,
        trial_end=None,
        current_period_end=None,
        cancel_at_period_end=False,
    )


async def _team(app, **kw) -> int:
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, "team", **kw)
        await session.commit()
        return plan.id


async def _subscribe(app, tenant_id, plan_id, **kw) -> None:
    fields = {"provider_subscription_id": "sub_1", **kw}
    async with app.state.sm.db.session_factory() as session:
        session.add(Subscription(tenant_id=tenant_id, plan_id=plan_id, **fields))
        session.add(Customer(tenant_id=tenant_id, provider="stripe", provider_customer_id="cus_1"))
        await session.commit()


async def _suspend(app, tenant_id) -> None:
    async with app.state.sm.db.session_factory() as session:
        (await session.get(Tenant, tenant_id)).status = TenantStatus.SUSPENDED
        await session.commit()
    forget(None)


async def _post_webhook(app, fake, eid, sid="sub_1"):
    fake.events[eid] = WebhookEvent(
        id=eid, type="customer.subscription.updated", subscription_id=sid
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.post(c.WEBHOOK_PATH, content=eid.encode(), headers=HEADERS)


# ── Important 1: a billing-suspended owner can still reach the portal ──


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


# ── Important 2: price edits and unknown prices ──


async def test_price_change_refused_while_subscribed(app):
    team = await _team(app)
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        await session.commit()
    await _subscribe(app, tenant.id, team, interval="month")
    async with app.state.sm.db.session_factory() as session:
        data = PlanIn(
            key="team",
            name="Team",
            pricing_model="flat",
            stripe_price_month="price_new",
            stripe_price_year="price_team_y",
        )
        with pytest.raises(PlanError) as exc:
            await PlanService(session).update(team, data)
        assert (exc.value.code, exc.value.status_code) == ("price_in_use", 409)
        # The yearly price nobody pays on can still change.
        ok = PlanIn(
            key="team",
            name="Team",
            pricing_model="flat",
            stripe_price_month="price_team_m",
            stripe_price_year="price_new_y",
        )
        assert (await PlanService(session).update(team, ok)).stripe_price_year == "price_new_y"


async def test_lapsing_snapshot_with_unknown_price_still_applies(app, fake):
    team = await _team(app)
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        await session.commit()
    await _subscribe(app, tenant.id, team)
    fake.snapshots["sub_1"] = _snap(tenant.id, status="canceled", price="price_gone")
    response = await _post_webhook(app, fake, "evt_1")
    assert response.status_code == 200, response.text
    async with app.state.sm.db.session_factory() as session:
        sub = (await session.execute(select(Subscription))).scalar_one()
        assert (sub.status, sub.plan_id) == ("canceled", team)


# ── Important 3: one trial per organisation ──


async def test_trial_only_once(app, user_client, fake):
    team = await _team(app, trial_days=14)
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await _subscribe(app, tenant["id"], team, status="canceled")
        await arm_csrf(owner)
        response = await owner.post("/api/billing/checkout", json={"plan_id": team})
        assert response.status_code == 200, response.text
    assert fake.called("create_checkout")[-1]["trial_days"] == 0


# ── Important 4: no second live subscription ──


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


# ── re-graded minors ──


async def test_foreign_subscription_is_acknowledged_not_retried(app, fake):
    fake.snapshots["sub_1"] = SubscriptionSnapshot(
        "sub_1", "cus_stranger", None, "active", "price_x", 1, None, None, False
    )
    response = await _post_webhook(app, fake, "evt_1")
    assert response.status_code == 200
    async with app.state.sm.db.session_factory() as session:
        row = await session.get(EventRow, "evt_1")
        assert "unknown_tenant" in row.error
        assert row.processed_at is not None


async def test_lapse_for_unknown_price_without_local_row_is_acknowledged(app, fake):
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        await session.commit()
    fake.snapshots["sub_1"] = _snap(tenant.id, status="canceled", price="price_gone")
    response = await _post_webhook(app, fake, "evt_1")
    assert response.status_code == 200, response.text
    async with app.state.sm.db.session_factory() as session:
        row = await session.get(EventRow, "evt_1")
        assert "nothing_to_apply" in row.error
        assert row.processed_at is not None
        assert (await session.execute(select(Subscription))).first() is None


async def test_status_seats_count_pending_invitations(app, user_client):
    async with user_client("owner@x.io") as (owner, _):
        await create_tenant(owner)
        invite = await owner.post(
            "/api/tenants/current/invitations", json={"email": "m@x.io", "role": "member"}
        )
        assert invite.status_code == 201, invite.text
        assert (await owner.get("/api/billing/status")).json()["seats"]["used"] == 2


async def test_webhook_pushes_drifted_seat_quantity(app, fake):
    team = await _team(app, pricing_model="per_seat")
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session, members=3)
        await session.commit()
    await _subscribe(app, tenant.id, team)
    fake.snapshots["sub_1"] = _snap(tenant.id, quantity=1)
    assert (await _post_webhook(app, fake, "evt_1")).status_code == 200
    assert fake.called("set_quantity") == [{"subscription_id": "sub_1", "quantity": 3}]


async def test_plan_rows_unchanged(app):
    async with app.state.sm.db.session_factory() as session:
        assert len((await session.execute(select(Plan))).scalars().all()) == 1
