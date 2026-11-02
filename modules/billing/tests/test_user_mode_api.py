"""``subject_mode = "user"``: every request entry point bills the signed-in user (#274)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from api_helpers import arm_csrf
from fake_provider import FakeProvider
from helpers import make_plan
from quota_helpers import PREFIX
from sm_billing.contracts.provider import SubscriptionSnapshot
from sm_billing.errors import BillingError
from sm_billing.models import Customer, Subscription, UsageEvent
from sm_billing.subjects import subject_for_user
from sqlalchemy import select
from subscription_helpers import _fake
from usage_helpers import METER, events


@pytest.fixture
def fake(user_mode_app) -> FakeProvider:
    return _fake(user_mode_app)


async def limit_plan(app, subject: str, limit: int) -> None:
    """``subject`` on a plan of its own that allows ``limit`` of the test meter."""
    async with app.state.sm.db.session_factory() as session:
        key = f"metered-{limit}-{subject[-8:]}"
        plan = await make_plan(session, key, limits={METER: limit})
        session.add(Subscription(tenant_id=subject, plan_id=plan.id))
        await session.commit()


async def _team(app) -> int:
    async with app.state.sm.db.session_factory() as session:
        team = await make_plan(session, "team")
        await session.commit()
        return team.id


async def test_status_is_per_user(user_mode_app, user_client):
    async with user_client("a@x.io") as (a, a_id), user_client("b@x.io") as (b, _):
        await limit_plan(user_mode_app, subject_for_user(a_id), 5)
        assert (await a.get("/api/billing/status")).json()["plan"]["key"].startswith("metered")
        assert (await b.get("/api/billing/status")).json()["plan"]["key"] == "free"
        # The page renders for a signed-in user; there is no organisation to pick.
        page = await a.get("/billing/", headers={"X-Inertia": "true"})
        assert page.status_code == 200, page.text
        props = page.json()["props"]
        assert props["status"]["plan"]["key"].startswith("metered")
        assert props["can_manage"] is True


async def test_checkout_and_change_plan_act_on_own_subject(user_mode_app, user_client, fake):
    team = await _team(user_mode_app)
    async with user_mode_app.state.sm.db.session_factory() as session:
        pro = (await make_plan(session, "pro")).id
        await session.commit()
    async with user_client("a@x.io") as (a, a_id), user_client("b@x.io") as (b, b_id):
        subject = subject_for_user(a_id)
        await arm_csrf(a)
        response = await a.post("/api/billing/checkout", json={"plan_id": team})
        assert response.status_code == 200, response.text
        assert fake.called("create_checkout")[-1]["tenant_id"] == subject
        async with user_mode_app.state.sm.db.session_factory() as session:
            assert await session.get(Customer, subject) is not None
            session.add(
                Subscription(tenant_id=subject, plan_id=team, provider_subscription_id="sub_1")
            )
            await session.commit()
        fake.snapshots["sub_1"] = fake_snapshot(subject, "price_pro_m")
        changed = await a.post("/api/billing/change-plan", json={"plan_id": pro})
        assert changed.status_code == 200, changed.text
        assert changed.json()["plan"]["key"] == "pro"
        # B has no subscription of their own: A's is not theirs to change.
        await arm_csrf(b)
        other = await b.post("/api/billing/change-plan", json={"plan_id": team})
        assert other.json()["detail"] == "no_subscription"
    async with user_mode_app.state.sm.db.session_factory() as session:
        rows = (await session.execute(select(Subscription.tenant_id))).scalars().all()
    assert rows == [subject]
    assert subject_for_user(b_id) not in rows


def fake_snapshot(subject: str, price: str) -> SubscriptionSnapshot:
    return SubscriptionSnapshot(
        id="sub_1",
        customer_id="cus_1",
        tenant_id=subject,
        status="active",
        price_id=price,
        quantity=1,
        trial_end=None,
        current_period_end=None,
        cancel_at_period_end=False,
    )


async def test_usage_is_per_user(user_mode_app, quota_app, user_client):
    async with user_client("a@x.io") as (a, a_id), user_client("b@x.io") as (b, b_id):
        await limit_plan(quota_app, subject_for_user(a_id), 5)
        await limit_plan(quota_app, subject_for_user(b_id), 5)
        assert (await a.get(f"{PREFIX}/ok")).status_code == 200
        a_usage = (await a.get("/api/billing/usage")).json()
        b_usage = (await b.get("/api/billing/usage")).json()
    assert [m["used"] for m in a_usage] == [1]
    assert [m["used"] for m in b_usage] == [0]


async def test_requires_quota_charges_the_caller(user_mode_app, quota_app, user_client):
    factory = quota_app.state.sm.db.session_factory
    async with user_client("a@x.io") as (a, a_id):
        await limit_plan(quota_app, subject_for_user(a_id), 1)
        assert (await a.get(f"{PREFIX}/ok")).json()["used"] == 1
        assert (await a.get(f"{PREFIX}/ok")).status_code == 402
    assert await events(factory, subject_for_user(a_id)) == 1
    assert await events(factory, "default") == 0


async def test_two_users_same_key_are_separate(user_mode_app, quota_app, user_client, runs):
    factory = quota_app.state.sm.db.session_factory
    headers = {"Idempotency-Key": "same-key"}
    async with user_client("a@x.io") as (a, a_id), user_client("b@x.io") as (b, b_id):
        for user_id in (a_id, b_id):
            await limit_plan(quota_app, subject_for_user(user_id), 5)
        assert (await a.get(f"{PREFIX}/count", headers=headers)).json() == {"used": 1}
        assert (await b.get(f"{PREFIX}/count", headers=headers)).json() == {"used": 1}
    assert runs == [1, 1]
    assert await events(factory, subject_for_user(a_id)) == 1
    assert await events(factory, subject_for_user(b_id)) == 1


async def test_signed_out_user_mode_is_401(user_mode_app, quota_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=quota_app), base_url="http://testserver"
    ) as anon:
        assert (await anon.get(f"{PREFIX}/ok")).status_code == 401
        assert (await anon.get("/api/billing/status")).status_code == 401
    from sm_billing.subjects import for_request

    # Past the auth gate (a public path, say) the subject itself refuses.
    request = SimpleNamespace(state=SimpleNamespace(), app=quota_app)
    with pytest.raises(BillingError) as exc:
        for_request(request)
    assert (exc.value.code, exc.value.status_code) == ("subject_required", 401)
    async with quota_app.state.sm.db.session_factory() as session:
        assert (await session.execute(select(UsageEvent))).first() is None


async def test_get_context_without_a_user_is_subject_required(user_mode_app):
    from sm_billing.deps import get_context

    request = SimpleNamespace(state=SimpleNamespace(), scope={}, app=user_mode_app)
    with pytest.raises(BillingError) as exc:
        await get_context(request, db=None)
    assert (exc.value.code, exc.value.status_code) == ("subject_required", 401)
