"""Webhook endpoint + sync, driven by the scripted FakeProvider."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fake_provider import GOOD_SIGNATURE, SIGNATURE_HEADER, FakeProvider
from helpers import make_plan, make_sub, make_tenant
from simple_module_core.public_routes import PublicRouteRegistry
from sm_billing import constants as c
from sm_billing.contracts.provider import SubscriptionSnapshot, WebhookEvent
from sm_billing.models import Customer, Plan, Subscription
from sm_billing.models import WebhookEvent as EventRow
from sm_billing.module import BillingModule
from sqlalchemy import select
from tenants.constants import TenantStatus
from tenants.models import Tenant

URL = c.WEBHOOK_PATH
HEADERS = {SIGNATURE_HEADER: GOOD_SIGNATURE}


@pytest.fixture
def fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as c_:
        yield c_


@pytest.fixture
async def world(app):
    """A tenant and a paid plan, committed."""
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        plan = await make_plan(session, "team", limits={"tenants.seats": 10})
        await session.commit()
        return tenant.id, plan.id


def snap(tenant_id: str | None, *, status="active", price="price_team_m", sid="sub_1", **kw):
    return SubscriptionSnapshot(
        id=sid,
        customer_id=kw.get("customer_id", "cus_1"),
        tenant_id=tenant_id,
        status=status,
        price_id=price,
        quantity=kw.get("quantity", 3),
        trial_end=None,
        current_period_end=datetime(2026, 11, 1, tzinfo=UTC),
        cancel_at_period_end=False,
    )


def event(fake: FakeProvider, eid: str, sid: str = "sub_1", etype="customer.subscription.updated"):
    fake.events[eid] = WebhookEvent(id=eid, type=etype, subscription_id=sid)
    return eid.encode()


async def _sub(app, tenant_id) -> Subscription | None:
    async with app.state.sm.db.session_factory() as session:
        stmt = select(Subscription).where(Subscription.tenant_id == tenant_id)
        return (await session.execute(stmt)).scalar_one_or_none()


async def _event_row(app, eid) -> EventRow | None:
    async with app.state.sm.db.session_factory() as session:
        return await session.get(EventRow, eid)


def test_webhook_path_is_public():
    registry = PublicRouteRegistry()
    BillingModule().register_public_routes(registry)
    assert registry.matches("POST", URL)
    assert not registry.matches("GET", URL)


async def test_bad_signature_is_400(client, fake):
    response = await client.post(URL, content=event(fake, "evt_1"), headers={})
    assert response.status_code == 400


async def test_first_delivery_creates_subscription(app, client, fake, world):
    tenant_id, plan_id = world
    fake.snapshots["sub_1"] = snap(tenant_id)
    response = await client.post(URL, content=event(fake, "evt_1"), headers=HEADERS)
    assert response.status_code == 200, response.text
    sub = await _sub(app, tenant_id)
    assert (sub.plan_id, sub.status, sub.interval, sub.quantity) == (plan_id, "active", "month", 3)
    assert sub.provider_subscription_id == "sub_1"
    assert sub.synced_at is not None
    async with app.state.sm.db.session_factory() as session:
        customer = await session.get(Customer, tenant_id)
        assert customer.provider_customer_id == "cus_1"
    assert (await _event_row(app, "evt_1")).processed_at is not None


async def test_duplicate_event_is_a_no_op(app, client, fake, world):
    tenant_id, _ = world
    fake.snapshots["sub_1"] = snap(tenant_id)
    body = event(fake, "evt_1")
    await client.post(URL, content=body, headers=HEADERS)
    again = await client.post(URL, content=body, headers=HEADERS)
    assert again.status_code == 200
    assert len(fake.called("fetch_subscription")) == 1


async def test_failure_records_error_and_replay_converges(app, client, fake, world):
    tenant_id, _ = world
    body = event(fake, "evt_1")
    fake.fail.add("fetch_subscription")
    failed = await client.post(URL, content=body, headers=HEADERS)
    assert failed.status_code == 500
    row = await _event_row(app, "evt_1")
    assert row.processed_at is None
    assert "fetch_subscription failed" in row.error
    fake.fail.clear()
    fake.snapshots["sub_1"] = snap(tenant_id)
    replay = await client.post(URL, content=body, headers=HEADERS)
    assert replay.status_code == 200
    assert (await _event_row(app, "evt_1")).error is None
    assert (await _sub(app, tenant_id)).status == "active"


async def test_out_of_order_events_write_current_state(app, client, fake, world):
    """The payload is ignored; whatever arrives last, the fetched state wins."""
    tenant_id, _ = world
    fake.snapshots["sub_1"] = snap(tenant_id, status="past_due")
    await client.post(URL, content=event(fake, "evt_new"), headers=HEADERS)
    fake.snapshots["sub_1"] = snap(tenant_id, status="active")
    await client.post(URL, content=event(fake, "evt_old"), headers=HEADERS)
    assert (await _sub(app, tenant_id)).status == "active"


async def test_unknown_price_records_error(app, client, fake, world):
    tenant_id, _ = world
    fake.snapshots["sub_1"] = snap(tenant_id, price="price_nobody_sells")
    response = await client.post(URL, content=event(fake, "evt_1"), headers=HEADERS)
    assert response.status_code == 500
    assert "unknown_price" in (await _event_row(app, "evt_1")).error
    assert await _sub(app, tenant_id) is None


async def test_tenant_found_through_customer(app, client, fake, world):
    tenant_id, _ = world
    async with app.state.sm.db.session_factory() as session:
        session.add(Customer(tenant_id=tenant_id, provider="stripe", provider_customer_id="cus_9"))
        await session.commit()
    fake.snapshots["sub_1"] = snap(None, customer_id="cus_9")
    response = await client.post(URL, content=event(fake, "evt_1"), headers=HEADERS)
    assert response.status_code == 200
    assert (await _sub(app, tenant_id)) is not None


async def test_deleted_subscription_falls_back_to_default(app, client, fake, world):
    tenant_id, _ = world
    fake.snapshots["sub_1"] = snap(tenant_id, status="canceled")
    await client.post(
        URL,
        content=event(fake, "evt_1", etype="customer.subscription.deleted"),
        headers=HEADERS,
    )
    assert (await _sub(app, tenant_id)).status == "canceled"
    assert await app.state.tenants.entitlements.limit(tenant_id, "tenants.seats") is None


async def test_unpaid_suspends_tenant(app, client, fake, world):
    tenant_id, _ = world
    fake.snapshots["sub_1"] = snap(tenant_id, status="unpaid")
    await client.post(URL, content=event(fake, "evt_1"), headers=HEADERS)
    async with app.state.sm.db.session_factory() as session:
        assert (await session.get(Tenant, tenant_id)).status == TenantStatus.SUSPENDED


async def test_stale_canceled_snapshot_does_not_replace_live_subscription(app, client, fake, world):
    tenant_id, plan_id = world
    async with app.state.sm.db.session_factory() as session:
        tenant = await session.get(Tenant, tenant_id)
        plan = await session.get(Plan, plan_id)
        await make_sub(session, tenant, plan, provider_subscription_id="sub_new")
        await session.commit()
    fake.snapshots["sub_old"] = snap(tenant_id, status="canceled", sid="sub_old")
    response = await client.post(URL, content=event(fake, "evt_1", sid="sub_old"), headers=HEADERS)
    assert response.status_code == 200
    sub = await _sub(app, tenant_id)
    assert (sub.provider_subscription_id, sub.status) == ("sub_new", "active")


async def test_unhandled_event_type_is_acknowledged(app, client, fake):
    fake.events["evt_x"] = WebhookEvent(id="evt_x", type="invoice.created")
    response = await client.post(URL, content=b"evt_x", headers=HEADERS)
    assert response.status_code == 200
    assert fake.called("fetch_subscription") == []
    assert (await _event_row(app, "evt_x")).processed_at is not None


async def test_manual_provider_has_no_webhook(client):
    response = await client.post(URL, content=b"x", headers=HEADERS)
    assert response.status_code == 404
