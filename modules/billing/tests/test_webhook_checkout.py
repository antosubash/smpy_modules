"""``checkout.session.completed``: the tenant comes from the re-fetched session.

Only when the subscription carries none, and only when the session and the
subscription agree on the paying customer and that customer does not belong
to, or collide with, another tenant's (#123). Anyone can open a Checkout naming
any tenant (a Payment Link takes ``client_reference_id`` from its URL).
"""

from __future__ import annotations

import httpx
import pytest
from fake_provider import FakeProvider
from helpers import make_plan, make_tenant
from sm_billing import constants as c
from sm_billing.contracts.provider import CheckoutSnapshot, WebhookEvent
from sm_billing.models import Customer
from test_webhooks import HEADERS, URL, _sub, snap


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
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        plan = await make_plan(session, "team", limits={"tenants.seats": 10})
        await session.commit()
        return tenant.id, plan.id


def checkout_event(fake: FakeProvider, eid: str, cid: str = "cs_1") -> bytes:
    fake.events[eid] = WebhookEvent(
        id=eid, type=c.CHECKOUT_COMPLETED, subscription_id="sub_1", checkout_id=cid
    )
    return eid.encode()


async def test_checkout_tenant_comes_from_the_refetched_session(app, client, fake, world):
    tenant_id, _ = world
    fake.checkouts["cs_1"] = CheckoutSnapshot("cs_1", "sub_1", tenant_id, "cus_1")
    fake.snapshots["sub_1"] = snap(None)
    response = await client.post(URL, content=checkout_event(fake, "evt_1"), headers=HEADERS)
    assert response.status_code == 200, response.text
    assert fake.called("fetch_checkout") == [{"session_id": "cs_1"}]
    assert (await _sub(app, tenant_id)).provider_subscription_id == "sub_1"


async def test_checkout_metadata_tenant_wins_over_reference(app, client, fake, world):
    tenant_id, _ = world
    fake.checkouts["cs_1"] = CheckoutSnapshot("cs_1", "sub_1", "someone-else", "cus_1")
    fake.snapshots["sub_1"] = snap(tenant_id)
    await client.post(URL, content=checkout_event(fake, "evt_1"), headers=HEADERS)
    assert (await _sub(app, tenant_id)) is not None


async def test_checkout_event_without_session_id_uses_the_subscription(app, client, fake, world):
    tenant_id, _ = world
    fake.snapshots["sub_1"] = snap(tenant_id)
    fake.events["evt_1"] = WebhookEvent(
        id="evt_1", type=c.CHECKOUT_COMPLETED, subscription_id="sub_1"
    )
    response = await client.post(URL, content=b"evt_1", headers=HEADERS)
    assert response.status_code == 200, response.text
    assert fake.called("fetch_checkout") == []
    assert (await _sub(app, tenant_id)) is not None


async def test_checkout_without_subscription_is_acknowledged(app, client, fake, world):
    fake.checkouts["cs_1"] = CheckoutSnapshot("cs_1", None, world[0], "cus_1")
    response = await client.post(URL, content=checkout_event(fake, "evt_1"), headers=HEADERS)
    assert (response.status_code, response.json()["detail"]) == (200, "ignored_nothing_to_apply")
    assert fake.called("fetch_subscription") == []


async def _customer(app, tenant_id: str, cid: str) -> None:
    async with app.state.sm.db.session_factory() as session:
        session.add(Customer(tenant_id=tenant_id, provider="stripe", provider_customer_id=cid))
        await session.commit()


async def _customer_of(app, tenant_id: str) -> str | None:
    async with app.state.sm.db.session_factory() as session:
        row = await session.get(Customer, tenant_id)
        return row.provider_customer_id if row else None


async def test_checkout_gated_on_session_not_payload_subscription(app, client, fake, world):
    """No subscription id in the payload: the session is fetched and decides."""
    tenant_id, _ = world
    fake.events["evt_1"] = WebhookEvent(id="evt_1", type=c.CHECKOUT_COMPLETED, checkout_id="cs_1")
    fake.checkouts["cs_1"] = CheckoutSnapshot("cs_1", "sub_1", tenant_id, "cus_1")
    fake.snapshots["sub_1"] = snap(None)
    response = await client.post(URL, content=b"evt_1", headers=HEADERS)
    assert (response.status_code, response.json()["detail"]) == (200, "processed")
    assert fake.called("fetch_checkout") == [{"session_id": "cs_1"}]
    assert (await _sub(app, tenant_id)).provider_subscription_id == "sub_1"


async def test_reference_cannot_take_over_a_billed_tenant(app, client, fake, world):
    """A stranger's Checkout naming a tenant billed to cus_victim changes nothing."""
    tenant_id, _ = world
    await _customer(app, tenant_id, "cus_victim")
    fake.checkouts["cs_1"] = CheckoutSnapshot("cs_1", "sub_1", tenant_id, "cus_attacker")
    fake.snapshots["sub_1"] = snap(None, customer_id="cus_attacker")
    response = await client.post(URL, content=checkout_event(fake, "evt_1"), headers=HEADERS)
    assert (response.status_code, response.json()["detail"]) == (200, "ignored_customer_mismatch")
    assert await _sub(app, tenant_id) is None
    assert await _customer_of(app, tenant_id) == "cus_victim"


async def test_reference_cannot_move_another_tenants_customer(app, client, fake, world):
    tenant_id, _ = world
    async with app.state.sm.db.session_factory() as session:
        other = (await make_tenant(session, "other")).id
        await session.commit()
    await _customer(app, other, "cus_other")
    fake.checkouts["cs_1"] = CheckoutSnapshot("cs_1", "sub_1", tenant_id, "cus_other")
    fake.snapshots["sub_1"] = snap(None, customer_id="cus_other")
    response = await client.post(URL, content=checkout_event(fake, "evt_1"), headers=HEADERS)
    assert response.json()["detail"] == "ignored_customer_mismatch"
    assert (await _sub(app, tenant_id), await _customer_of(app, tenant_id)) == (None, None)
    assert await _customer_of(app, other) == "cus_other"


async def test_reference_needs_session_and_subscription_to_agree(app, client, fake, world):
    tenant_id, _ = world
    fake.checkouts["cs_1"] = CheckoutSnapshot("cs_1", "sub_1", tenant_id, "cus_1")
    fake.snapshots["sub_1"] = snap(None, customer_id="cus_2")
    response = await client.post(URL, content=checkout_event(fake, "evt_1"), headers=HEADERS)
    assert response.json()["detail"] == "ignored_customer_mismatch"
    assert await _sub(app, tenant_id) is None


async def test_reference_matching_stored_customer_applies(app, client, fake, world):
    tenant_id, _ = world
    await _customer(app, tenant_id, "cus_1")
    fake.checkouts["cs_1"] = CheckoutSnapshot("cs_1", "sub_1", tenant_id, "cus_1")
    fake.snapshots["sub_1"] = snap(None)
    response = await client.post(URL, content=checkout_event(fake, "evt_1"), headers=HEADERS)
    assert response.json()["detail"] == "processed"
