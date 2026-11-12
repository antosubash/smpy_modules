"""Provider return URLs need ``return_base_url`` outside development (#355).

Blank, Checkout's success/cancel URLs and the portal's return URL used to be
the request's own origin, which is the client's ``Host`` header, or the
internal host name behind a proxy without ``trusted_proxy``. Now only a
development or testing host falls back to it; anywhere else the session is
refused with 409 ``return_base_url_missing`` before the provider is called.
"""

from __future__ import annotations

import pytest
from sm_billing.models import Customer

from tests.support.api_helpers import arm_csrf, create_tenant
from tests.support.fake_provider import FakeProvider
from tests.support.subscription_helpers import _team


@pytest.fixture
def fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


def _configure(app, *, environment: str, base: str) -> None:
    app.state.sm.settings.environment = environment
    app.state.sm_billing.settings.return_base_url = base


async def _customer(app, tenant_id: str) -> None:
    async with app.state.sm.db.session_factory() as session:
        session.add(Customer(tenant_id=tenant_id, provider="stripe", provider_customer_id="cus_1"))
        await session.commit()


async def test_production_without_the_setting_refuses_both(app, user_client, fake):
    team = await _team(app)
    _configure(app, environment="production", base="")
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await _customer(app, tenant["id"])
        await arm_csrf(owner)
        checkout = await owner.post("/api/billing/checkout", json={"plan_id": team})
        portal = await owner.post("/api/billing/portal")
    for response in (checkout, portal):
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "return_base_url_missing"
    assert not fake.called("create_checkout") and not fake.called("portal_url")


@pytest.mark.parametrize("environment", ["production", "testing"])
async def test_the_setting_is_used_wherever_it_is_set(app, user_client, fake, environment):
    team = await _team(app)
    _configure(app, environment=environment, base="https://app.example.com")
    async with user_client("owner@x.io") as (owner, _):
        tenant = await create_tenant(owner)
        await _customer(app, tenant["id"])
        await arm_csrf(owner)
        checkout = await owner.post("/api/billing/checkout", json={"plan_id": team})
        portal = await owner.post("/api/billing/portal")
    assert checkout.status_code == portal.status_code == 200, (checkout.text, portal.text)
    assert fake.called("create_checkout")[-1]["success_url"].startswith("https://app.example.com/")
    assert fake.called("portal_url")[-1]["return_url"].startswith("https://app.example.com/")


@pytest.mark.parametrize("environment", ["development", "testing"])
async def test_development_falls_back_to_the_request(app, user_client, fake, environment):
    team = await _team(app)
    _configure(app, environment=environment, base="")
    async with user_client("owner@x.io") as (owner, _):
        await create_tenant(owner)
        await arm_csrf(owner)
        checkout = await owner.post("/api/billing/checkout", json={"plan_id": team})
    assert checkout.status_code == 200, checkout.text
    assert fake.called("create_checkout")[-1]["success_url"].startswith("http://")
