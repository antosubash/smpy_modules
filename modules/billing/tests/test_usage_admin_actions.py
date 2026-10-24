"""Admin usage writes: adjust (reason required, ledgered with the actor),
release a hold, recount a gauge — CSRF and ``billing.platform.manage``."""

from __future__ import annotations

import pytest
from api_helpers import arm_csrf, create_tenant
from sm_billing.models import UsageEvent, UsageGauge
from sqlalchemy import select, update
from usage_api_helpers import ADMIN, COUNTER, GAUGE, consume, define_meters, put_on_plan, reserve
from usage_helpers import in_use


@pytest.fixture(autouse=True)
def _meters(app):
    define_meters(app)


@pytest.fixture
async def admin(authenticated_client):
    await arm_csrf(authenticated_client, "/admin/billing/usage")
    return authenticated_client


@pytest.fixture
async def tenant(user_client) -> str:
    async with user_client("owner@x.io") as (owner, _):
        return (await create_tenant(owner))["id"]


async def _events(app, tenant_id: str) -> list[UsageEvent]:
    async with app.state.sm.db.session_factory() as session:
        stmt = select(UsageEvent).where(UsageEvent.tenant_id == tenant_id).order_by(UsageEvent.id)
        return list((await session.scalars(stmt)).all())


async def test_adjust_is_ledgered_with_reason_and_actor(app, admin, tenant):
    await put_on_plan(app, tenant, {COUNTER: 5})
    await consume(app, tenant, 5)
    response = await admin.post(
        f"{ADMIN}/{tenant}/adjust",
        json={"meter": COUNTER, "quantity": -2, "reason": "  goodwill credit  "},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"meter": COUNTER, "used": 3}
    adjust = (await _events(app, tenant))[-1]
    assert (adjust.kind, adjust.quantity, adjust.reason) == ("adjust", -2, "goodwill credit")
    assert adjust.source == "admin" and adjust.actor  # the admin's user id
    page = (await admin.get(f"{ADMIN}/{tenant}/events", params={"kind": "adjust"})).json()
    assert page["items"][0]["reason"] == "goodwill credit"
    # The credit makes room again.
    await consume(app, tenant, 2)


@pytest.mark.parametrize(
    "body",
    [
        {"meter": COUNTER, "quantity": 1, "reason": "   "},
        {"meter": COUNTER, "quantity": 1},
        {"meter": COUNTER, "quantity": 0, "reason": "zero"},
        {"meter": COUNTER, "quantity": 1, "reason": "x" * 501},
    ],
)
async def test_adjust_needs_a_reason_and_a_quantity(app, admin, tenant, body):
    response = await admin.post(f"{ADMIN}/{tenant}/adjust", json=body)
    assert response.status_code == 422
    assert await _events(app, tenant) == []


async def test_adjust_refuses_unknown_meters_and_tenants(app, admin, tenant):
    body = {"quantity": 1, "reason": "r"}
    gauge = await admin.post(f"{ADMIN}/{tenant}/adjust", json={**body, "meter": GAUGE})
    assert (gauge.status_code, gauge.json()["detail"]) == (400, "unknown_meter")
    unknown = await admin.post(f"{ADMIN}/{tenant}/adjust", json={**body, "meter": "nope"})
    assert unknown.status_code == 400
    ghost = await admin.post(f"{ADMIN}/{'f' * 32}/adjust", json={**body, "meter": COUNTER})
    assert (ghost.status_code, ghost.json()["detail"]) == (404, "tenant_not_found")


async def test_writes_need_csrf(app, authenticated_client, tenant):
    hold = await reserve(app, tenant)
    for url, body in (
        (f"{ADMIN}/{tenant}/adjust", {"meter": COUNTER, "quantity": 1, "reason": "r"}),
        (f"{ADMIN}/{tenant}/recount", {"meter": GAUGE}),
        (f"{ADMIN}/holds/{hold.id}/release", None),
    ):
        response = await authenticated_client.post(url, json=body)
        assert response.status_code == 403, url
    assert await in_use(app.state.sm.db.session_factory, tenant) == 1


async def test_writes_need_platform_manage(app, user_client, tenant):
    hold = await reserve(app, tenant)
    async with user_client("other@x.io") as (owner, _):
        await create_tenant(owner, "Other")
        await arm_csrf(owner)
        for url, body in (
            (f"{ADMIN}/{tenant}/adjust", {"meter": COUNTER, "quantity": 1, "reason": "r"}),
            (f"{ADMIN}/{tenant}/recount", {"meter": GAUGE}),
            (f"{ADMIN}/holds/{hold.id}/release", None),
        ):
            assert (await owner.post(url, json=body)).status_code == 403, url


async def test_release_returns_the_capacity_once(app, admin, tenant):
    hold = await reserve(app, tenant, 2)
    first = await admin.post(f"{ADMIN}/holds/{hold.id}/release")
    assert (first.status_code, first.json()) == (200, {"released": True})
    again = await admin.post(f"{ADMIN}/holds/{hold.id}/release")
    assert again.json() == {"released": False}
    assert await in_use(app.state.sm.db.session_factory, tenant) == 0
    missing = await admin.post(f"{ADMIN}/holds/{'0' * 32}/release")
    assert (missing.status_code, missing.json()["detail"]) == (404, "hold_not_found")


async def test_recount_repairs_drift(app, admin, tenant):
    factory = app.state.sm.db.session_factory
    await reserve(app, tenant)
    async with factory() as session:
        await session.execute(
            update(UsageGauge).where(UsageGauge.tenant_id == tenant).values(in_use=7)
        )
        await session.commit()
    response = await admin.post(f"{ADMIN}/{tenant}/recount", json={"meter": GAUGE})
    assert (response.status_code, response.json()) == (200, {"meter": GAUGE, "in_use": 1})
    assert await in_use(factory, tenant) == 1
    counter = await admin.post(f"{ADMIN}/{tenant}/recount", json={"meter": COUNTER})
    assert (counter.status_code, counter.json()["detail"]) == (400, "unknown_meter")
