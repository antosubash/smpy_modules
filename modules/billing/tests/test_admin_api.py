"""Platform-admin API and screens: plans, subscriptions, connection."""

from __future__ import annotations

import pytest
from api_helpers import arm_csrf, create_tenant, page_props
from fake_provider import FakeProvider
from helpers import make_plan, make_tenant
from sm_billing import crypto
from sm_billing.contracts.provider import PriceInfo, SubscriptionSnapshot
from sm_billing.providers.stripe import StripeProvider
from tenants.constants import TenantStatus
from tenants.models import Tenant

ADMIN = "/api/billing/admin"


def _plan(key="team", **kw):
    data = {
        "key": key,
        "name": key.title(),
        "pricing_model": "flat",
        "currency": "eur",
        "stripe_price_month": f"price_{key}_m",
        "limits": {"tenants.seats": 5},
    }
    data.update(kw)
    return data


@pytest.fixture
async def admin(authenticated_client):
    await arm_csrf(authenticated_client, "/admin/billing/plans")
    return authenticated_client


@pytest.fixture
def fake(app) -> FakeProvider:
    provider = FakeProvider()
    provider.prices["price_team_m"] = PriceInfo("price_team_m", "eur", "month", True)
    app.state.sm_billing.provider = provider
    return provider


async def test_admin_views_render(admin):
    plans = await page_props(admin, "/admin/billing/plans")
    assert [p["key"] for p in plans["plans"]] == ["free"]
    assert plans["known_limit_keys"] == ["tenants.seats"]
    subs = await page_props(admin, "/admin/billing/subscriptions")
    assert subs["rows"] == []
    conn = await page_props(admin, "/admin/billing/connection")
    assert conn["connection"]["webhook_path"] == "/billing/webhooks/stripe"


async def test_create_update_archive_plan(admin):
    created = await admin.post(f"{ADMIN}/plans", json=_plan())
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    updated = await admin.put(f"{ADMIN}/plans/{plan_id}", json=_plan(name="Team+"))
    assert updated.json()["name"] == "Team+"
    archived = await admin.post(f"{ADMIN}/plans/{plan_id}/archive")
    assert archived.json()["archived_at"] is not None
    listed = (await admin.get(f"{ADMIN}/plans")).json()
    assert {p["key"] for p in listed} == {"free", "team"}


async def test_plan_errors_map_to_codes(admin):
    bad = await admin.post(f"{ADMIN}/plans", json=_plan(stripe_price_month=None))
    assert (bad.status_code, bad.json()["detail"]) == (400, "paid_plan_needs_price")
    await admin.post(f"{ADMIN}/plans", json=_plan())
    dup = await admin.post(f"{ADMIN}/plans", json=_plan(stripe_price_month="other"))
    assert (dup.status_code, dup.json()["detail"]) == (409, "plan_key_taken")


async def test_prices_verified_under_stripe(admin, fake):
    unknown = await admin.post(f"{ADMIN}/plans", json=_plan("pro", stripe_price_month="price_x"))
    assert (unknown.status_code, unknown.json()["detail"]) == (400, "price_not_found")
    fake.prices["price_usd"] = PriceInfo("price_usd", "usd", "month", True)
    wrong = await admin.post(f"{ADMIN}/plans", json=_plan("pro", stripe_price_month="price_usd"))
    assert wrong.json() == {
        "detail": "price_mismatch",
        "price": "price_usd",
        "reason": "currency usd ≠ plan currency eur",
    }
    fake.prices["price_y"] = PriceInfo("price_y", "eur", "year", True)
    swapped = await admin.post(f"{ADMIN}/plans", json=_plan("pro", stripe_price_month="price_y"))
    assert swapped.json()["reason"] == "interval year ≠ month"
    ok = await admin.post(f"{ADMIN}/plans", json=_plan())
    assert ok.status_code == 201


async def test_tenant_owner_cannot_reach_admin(user_client):
    async with user_client("owner@x.io") as (owner, _):
        await create_tenant(owner)
        assert (await owner.get(f"{ADMIN}/plans")).status_code == 403
        assert (await owner.get("/admin/billing/plans")).status_code in (302, 303, 403)


async def test_subscriptions_list_and_assign_manual(app, admin):
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session, "acme", members=2)
        team = await make_plan(session, "team")
        await session.commit()
        tenant_id, team_id = tenant.id, team.id
    rows = (await admin.get(f"{ADMIN}/subscriptions")).json()
    assert [(r["tenant_slug"], r["plan_key"], r["status"], r["members"]) for r in rows] == [
        ("acme", "free", None, 2)
    ]
    assigned = await admin.post(
        f"{ADMIN}/subscriptions/{tenant_id}/assign",
        json={"plan_id": team_id, "status": "unpaid"},
    )
    assert assigned.status_code == 200, assigned.text
    assert (assigned.json()["plan_key"], assigned.json()["status"]) == ("team", "unpaid")
    assert assigned.json()["tenant_status"] == TenantStatus.SUSPENDED
    again = await admin.post(
        f"{ADMIN}/subscriptions/{tenant_id}/assign", json={"plan_id": team_id, "status": "active"}
    )
    assert again.json()["tenant_status"] == TenantStatus.ACTIVE
    filtered = (await admin.get(f"{ADMIN}/subscriptions", params={"status": "past_due"})).json()
    assert filtered == []


async def test_assign_refused_under_stripe_and_resync_works(app, admin, fake):
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        team = await make_plan(session, "team")
        await session.commit()
        tenant_id, team_id = tenant.id, team.id
    refused = await admin.post(
        f"{ADMIN}/subscriptions/{tenant_id}/assign", json={"plan_id": team_id}
    )
    assert refused.json()["detail"] == "provider_managed"
    nothing = await admin.post(f"{ADMIN}/subscriptions/{tenant_id}/resync")
    assert nothing.json()["detail"] == "no_provider_subscription"
    fake.snapshots["sub_1"] = SubscriptionSnapshot(
        "sub_1", "cus_1", tenant_id, "active", "price_team_m", 1, None, None, False
    )
    async with app.state.sm.db.session_factory() as session:
        from sm_billing.models import Subscription

        session.add(
            Subscription(
                tenant_id=tenant_id,
                plan_id=team_id,
                status="incomplete",
                provider_subscription_id="sub_1",
            )
        )
        await session.commit()
    synced = await admin.post(f"{ADMIN}/subscriptions/{tenant_id}/resync")
    assert synced.json()["status"] == "active"


async def test_assign_unknown_tenant_404(admin):
    response = await admin.post(f"{ADMIN}/subscriptions/nope/assign", json={"plan_id": 1})
    assert response.status_code == 404


async def test_connection_encrypts_and_masks(app, admin):
    saved = await admin.put(
        f"{ADMIN}/connection",
        json={
            "stripe_secret_key": " sk_test_1\n",
            "stripe_webhook_secret": "whsec_1",
            "return_base_url": "https://app.example.com/",
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["has_secret_key"], body["has_webhook_secret"]) == (True, True)
    assert "sk_test_1" not in saved.text
    stored = app.state.sm_billing.settings
    assert stored.stripe_secret_key.startswith(crypto.ENC_PREFIX)
    assert crypto.decrypt_value(stored.stripe_secret_key, "x") == "sk_test_1"
    assert stored.return_base_url == "https://app.example.com"
    keep = await admin.put(f"{ADMIN}/connection", json={})
    assert keep.json()["has_secret_key"] is True
    cleared = await admin.put(f"{ADMIN}/connection", json={"clear_webhook_secret": True})
    assert cleared.json()["has_webhook_secret"] is False


async def test_connection_save_rebuilds_stripe_provider(app, admin):
    app.state.sm_billing.settings = app.state.sm_billing.settings.model_copy(
        update={"provider": "stripe"}
    )
    await admin.put(
        f"{ADMIN}/connection",
        json={"stripe_secret_key": "sk_test_1", "stripe_webhook_secret": "whsec_1"},
    )
    assert isinstance(app.state.sm_billing.provider, StripeProvider)
    conn = (await admin.get(f"{ADMIN}/connection")).json()
    assert (conn["active_provider"], conn["provider_error"]) == ("stripe", "")


async def test_suspended_tenant_listed(app, admin):
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        tenant.status = TenantStatus.SUSPENDED
        await session.commit()
        assert (await session.get(Tenant, tenant.id)).status == TenantStatus.SUSPENDED
    rows = (await admin.get(f"{ADMIN}/subscriptions")).json()
    assert rows[0]["tenant_status"] == TenantStatus.SUSPENDED
