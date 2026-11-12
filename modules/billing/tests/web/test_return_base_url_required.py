"""Provider return URLs need a configured origin on a production single-tenant host (#355).

Blank, Checkout's success/cancel URLs and the portal's return URL used to be
the request's own origin, which is the client's ``Host`` header, or the
internal host name behind a proxy without ``trusted_proxy``. Now the order is
``return_base_url``, then (single-tenant) the host's ``public_base_url``, then
the request's origin only on a multi-tenant host or in development/testing;
anything else is 409 ``return_base_url_missing`` before the provider is called,
and after every other refusal.

The suite's host is multi-tenant, so the single-tenant cases pin
``deps.is_multi_tenant``.
"""

from __future__ import annotations

import pytest
from sm_billing.models import Customer
from sm_billing.web import deps

from tests.support.api_helpers import arm_csrf, create_tenant
from tests.support.fake_provider import FakeProvider
from tests.support.subscription_helpers import _team


@pytest.fixture
def fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


@pytest.fixture
def single(monkeypatch):
    monkeypatch.setattr(deps, "is_multi_tenant", lambda app: False)


def _configure(app, *, environment: str, base: str, host_base: str = "") -> None:
    app.state.sm.settings.environment = environment
    app.state.sm.settings.public_base_url = host_base
    app.state.sm_billing.settings.return_base_url = base


async def _customer(app, tenant_id: str) -> None:
    async with app.state.sm.db.session_factory() as session:
        session.add(Customer(tenant_id=tenant_id, provider="stripe", provider_customer_id="cus_1"))
        await session.commit()


async def test_production_without_the_setting_refuses_both(app, user_client, fake, single):
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


async def test_the_hosts_public_base_url_satisfies_it(app, user_client, fake, single):
    team = await _team(app)
    _configure(app, environment="production", base="", host_base="https://site.example/")
    async with user_client("owner@x.io") as (owner, _):
        await create_tenant(owner)
        await arm_csrf(owner)
        checkout = await owner.post("/api/billing/checkout", json={"plan_id": team})
    assert checkout.status_code == 200, checkout.text
    assert fake.called("create_checkout")[-1]["success_url"].startswith("https://site.example/")


async def test_a_multi_tenant_host_keeps_the_request_origin(app, user_client, fake):
    """Blank is right there: each organisation can be on its own host. The
    host's ``public_base_url`` names one origin, so it is not used either."""
    team = await _team(app)
    _configure(app, environment="production", base="", host_base="https://site.example")
    async with user_client("owner@x.io") as (owner, _):
        await create_tenant(owner)
        await arm_csrf(owner)
        checkout = await owner.post("/api/billing/checkout", json={"plan_id": team})
    assert checkout.status_code == 200, checkout.text
    assert fake.called("create_checkout")[-1]["success_url"].startswith("http://test")


async def test_other_refusals_come_first(app, user_client, single):
    """The origin is resolved only when the provider needs it: a manual provider
    is still ``checkout_unavailable``, an unknown plan ``plan_not_found`` and a
    portal without a customer ``no_customer``."""
    _configure(app, environment="production", base="")
    async with user_client("owner@x.io") as (owner, _):
        await create_tenant(owner)
        await arm_csrf(owner)
        manual = await owner.post("/api/billing/checkout", json={"plan_id": 1})
        app.state.sm_billing.provider = FakeProvider()
        unknown = await owner.post("/api/billing/checkout", json={"plan_id": 99999})
        portal = await owner.post("/api/billing/portal")
    assert (manual.status_code, manual.json()["detail"]) == (409, "checkout_unavailable")
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "plan_not_found")
    assert (portal.status_code, portal.json()["detail"]) == (409, "no_customer")
