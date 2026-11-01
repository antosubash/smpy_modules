"""Platform admin in ``subject_mode = "user"``: list, assign and usage by user (#274)."""

from __future__ import annotations

import uuid

import pytest
from api_helpers import page_props
from conftest import make_user
from helpers import make_plan
from sm_billing.constants import PricingModel
from sm_billing.models import Subscription
from sm_billing.subjects import subject_for_user
from usage_api_helpers import ADMIN as USAGE
from usage_api_helpers import COUNTER, consume, define_meters, put_on_plan

ADMIN = "/api/billing/admin"


async def _plan(app, key: str = "team", **kw) -> int:
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, key, **kw)
        await session.commit()
        return plan.id


def _by_subject(rows: list[dict]) -> dict[str, dict]:
    return {r["tenant_id"]: r for r in rows}


async def test_admin_lists_users_in_user_mode(user_mode_app, admin):
    app = user_mode_app
    a = subject_for_user(await make_user(app, "a@x.io"))
    b = subject_for_user(await make_user(app, "b@x.io"))
    team = await _plan(app)
    async with app.state.sm.db.session_factory() as session:
        session.add(Subscription(tenant_id=a, plan_id=team, status="active"))
        await session.commit()

    rows = _by_subject((await admin.get(f"{ADMIN}/subscriptions")).json())
    assert {a, b} <= rows.keys()
    assert all(s.startswith("user:") for s in rows)  # users only, no organisations
    assert (rows[a]["tenant_name"], rows[a]["tenant_slug"], rows[a]["tenant_status"]) == (
        "a@x.io",
        "",
        "active",
    )
    assert (rows[a]["plan_key"], rows[a]["status"]) == ("team", "active")
    assert (rows[b]["plan_key"], rows[b]["status"]) == ("free", None)

    active = (await admin.get(f"{ADMIN}/subscriptions", params={"status": "active"})).json()
    assert [r["tenant_id"] for r in active] == [a]
    paged = (await admin.get(f"{ADMIN}/subscriptions", params={"offset": len(rows)})).json()
    assert paged == []

    props = await page_props(admin, "/admin/billing/subscriptions")
    assert props["subject_mode"] == "user"
    assert a in {r["tenant_id"] for r in props["rows"]}


async def test_a_user_disabled_with_disabled_at_is_inactive(user_mode_app, admin):
    """A user the framework treats as disabled (``disabled_at`` set) is listed inactive."""
    from datetime import UTC, datetime

    from sqlalchemy import update
    from users.models import User

    app = user_mode_app
    uid = await make_user(app, "gone@x.io")
    async with app.state.sm.db.session_factory() as session:
        await session.execute(
            update(User).where(User.id == uuid.UUID(uid)).values(disabled_at=datetime.now(UTC))
        )
        await session.commit()
    rows = _by_subject((await admin.get(f"{ADMIN}/subscriptions")).json())
    assert rows[subject_for_user(uid)]["tenant_status"] == "inactive"


async def test_tenant_mode_lists_say_tenant(app, admin):
    props = await page_props(admin, "/admin/billing/subscriptions")
    assert props["subject_mode"] == "tenant"


async def test_admin_assigns_a_plan_to_a_user(user_mode_app, admin):
    app = user_mode_app
    subject = subject_for_user(await make_user(app, "a@x.io"))
    team = await _plan(app)
    response = await admin.post(
        f"{ADMIN}/subscriptions/{subject}/assign", json={"plan_id": team, "status": "unpaid"}
    )
    assert response.status_code == 200, response.text
    row = response.json()
    assert (row["tenant_id"], row["tenant_name"], row["plan_key"], row["status"]) == (
        subject,
        "a@x.io",
        "team",
        "unpaid",
    )
    # A user is never suspended: unpaid downgrades instead.
    assert row["tenant_status"] == "active"


async def test_admin_assign_refuses_a_per_seat_plan_for_a_user(user_mode_app, admin):
    app = user_mode_app
    subject = subject_for_user(await make_user(app, "a@x.io"))
    seats = await _plan(app, "seats", pricing_model=PricingModel.PER_SEAT)
    response = await admin.post(f"{ADMIN}/subscriptions/{subject}/assign", json={"plan_id": seats})
    assert (response.status_code, response.json()["detail"]) == (422, "per_seat_requires_tenant")


async def test_usage_admin_reads_a_user_subject(user_mode_app, admin):
    app = user_mode_app
    define_meters(app)
    subject = subject_for_user(await make_user(app, "a@x.io"))
    await put_on_plan(app, subject, {COUNTER: 5})
    await consume(app, subject, 3)

    page = (await admin.get(USAGE)).json()
    row = next(r for r in page["items"] if r["tenant_id"] == subject)
    assert (row["tenant_name"], row["tenant_slug"], row["used"]) == ("a@x.io", "", 3)
    assert (await admin.get(USAGE, params={"q": "a@x"})).json()["total"] == 1

    adjusted = await admin.post(
        f"{USAGE}/{subject}/adjust", json={"meter": COUNTER, "quantity": -1, "reason": "credit"}
    )
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["used"] == 2
    events = (await admin.get(f"{USAGE}/{subject}/events")).json()
    assert events["items"][0]["kind"] == "adjust"


@pytest.mark.parametrize("subject", [f"user:{uuid.UUID(int=7)}", "user:not-a-uuid"])
async def test_unknown_user_subject_is_404(user_mode_app, admin, subject):
    define_meters(user_mode_app)
    team = await _plan(user_mode_app)
    assigned = await admin.post(f"{ADMIN}/subscriptions/{subject}/assign", json={"plan_id": team})
    assert (assigned.status_code, assigned.json()["detail"]) == (404, "tenant_not_found")
    adjusted = await admin.post(
        f"{USAGE}/{subject}/adjust", json={"meter": COUNTER, "quantity": 1, "reason": "r"}
    )
    assert (adjusted.status_code, adjusted.json()["detail"]) == (404, "tenant_not_found")


async def test_user_subject_is_not_assignable_in_tenant_mode(app, admin):
    """The tenant-mode list holds organisations only; a user subject is no row of it."""
    subject = subject_for_user(await make_user(app, "a@x.io"))
    team = await _plan(app)
    response = await admin.post(f"{ADMIN}/subscriptions/{subject}/assign", json={"plan_id": team})
    assert response.status_code == 404


async def test_default_on_a_multi_tenant_host_is_404(app, admin):
    """``default`` is no organisation once the host is multi-tenant."""
    define_meters(app)
    team = await _plan(app)
    assigned = await admin.post(f"{ADMIN}/subscriptions/default/assign", json={"plan_id": team})
    assert (assigned.status_code, assigned.json()["detail"]) == (404, "tenant_not_found")
    adjusted = await admin.post(
        f"{USAGE}/default/adjust", json={"meter": COUNTER, "quantity": 1, "reason": "r"}
    )
    assert (adjusted.status_code, adjusted.json()["detail"]) == (404, "tenant_not_found")
