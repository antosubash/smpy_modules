"""The owner Billing page in user mode offers only what a user can buy (#274)."""

from __future__ import annotations

from api_helpers import create_tenant, page_props
from helpers import make_plan


async def _seats_and_solo(app) -> None:
    async with app.state.sm.db.session_factory() as session:
        await make_plan(session, "seats", pricing_model="per_seat")
        await make_plan(session, "solo")
        await session.commit()


async def test_user_mode_page_hides_per_seat_plans(user_mode_app, user_client):
    await _seats_and_solo(user_mode_app)
    async with user_client("a@x.io") as (client, _):
        props = await page_props(client, "/billing/")
    assert sorted(p["key"] for p in props["plans"]) == ["free", "solo"]
    assert props["subject_mode"] == "user"


async def test_tenant_mode_page_keeps_per_seat_plans(app, user_client):
    await _seats_and_solo(app)
    async with user_client("owner@x.io") as (owner, _):
        await create_tenant(owner)
        props = await page_props(owner, "/billing/")
    assert sorted(p["key"] for p in props["plans"]) == ["free", "seats", "solo"]
    assert props["subject_mode"] == "tenant"


async def test_user_mode_without_view_is_forbidden_not_sent_to_tenants(
    user_mode_app, user_client, monkeypatch
):
    """No organisations in user mode: the tenant chooser is never the answer."""
    from sm_billing.endpoints import views

    monkeypatch.setattr(views, "_perm", lambda _request, _permission: False)
    async with user_client("a@x.io") as (client, _):
        response = await client.get("/billing/", follow_redirects=False)
    assert response.status_code == 403
    assert "location" not in response.headers


async def test_tenant_mode_without_view_still_redirects(app, user_client, monkeypatch):
    from sm_billing.endpoints import views

    monkeypatch.setattr(views, "_perm", lambda _request, _permission: False)
    async with user_client("owner@x.io") as (owner, _):
        response = await owner.get("/billing/", follow_redirects=False)
    assert response.status_code == 303
