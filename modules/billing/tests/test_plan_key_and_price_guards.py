"""Plan keys and prices stay unique under a race, and a price someone pays on
cannot be edited away."""

from __future__ import annotations

import pytest
from api_helpers import arm_csrf
from helpers import make_plan, make_tenant
from sm_billing.plans import PlanError, PlanService
from sm_billing.schemas import PlanIn
from subscription_helpers import _subscribe, _team

ADMIN = "/api/billing/admin"


def _data(key: str = "team", **kw) -> dict:
    data = {
        "key": key,
        "name": key.title(),
        "pricing_model": "flat",
        "currency": "eur",
        "stripe_price_month": f"price_{key}_new",
    }
    data.update(kw)
    return data


@pytest.fixture
async def admin(authenticated_client):
    await arm_csrf(authenticated_client, "/admin/billing/plans")
    return authenticated_client


async def _precreate(app, key: str = "team", **kw) -> None:
    """A second session commits the conflicting row — the race's other request."""
    async with app.state.sm.db.session_factory() as other:
        await make_plan(other, key, **kw)
        await other.commit()


def _skip_first_check(monkeypatch) -> None:
    """The first uniqueness check misses the row (it is not committed yet)."""
    real = PlanService._ensure_unique
    calls = {"n": 0}

    async def racy(self, data, plan_id):
        calls["n"] += 1
        if calls["n"] > 1:
            await real(self, data, plan_id)

    monkeypatch.setattr(PlanService, "_ensure_unique", racy)


def _skip_all_checks(monkeypatch) -> None:
    async def noop(self, data, plan_id):
        return None

    monkeypatch.setattr(PlanService, "_ensure_unique", noop)


# ── key and price races ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("skip", [_skip_first_check, _skip_all_checks])
async def test_create_key_race_is_409(app, monkeypatch, skip):
    await _precreate(app)
    skip(monkeypatch)
    async with app.state.sm.db.session_factory() as session:
        with pytest.raises(PlanError) as exc:
            await PlanService(session).create(PlanIn(**_data()))
        assert (exc.value.code, exc.value.status_code) == ("plan_key_taken", 409)
        # The savepoint rolled back; the request session is still usable.
        assert [p.key for p in await PlanService(session).list()] == ["free", "team"]


@pytest.mark.parametrize("skip", [_skip_first_check, _skip_all_checks])
async def test_create_price_race_is_409(app, monkeypatch, skip):
    await _precreate(app, "other", stripe_price_month="price_dup")
    skip(monkeypatch)
    async with app.state.sm.db.session_factory() as session:
        with pytest.raises(PlanError) as exc:
            await PlanService(session).create(PlanIn(**_data(stripe_price_month="price_dup")))
        assert (exc.value.code, exc.value.status_code) == ("price_taken", 409)


@pytest.mark.parametrize("skip", [_skip_first_check, _skip_all_checks])
async def test_update_price_race_is_409(app, monkeypatch, skip):
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, "team")
        await session.commit()
        plan_id = plan.id
    await _precreate(app, "other", stripe_price_month="price_dup")
    skip(monkeypatch)
    async with app.state.sm.db.session_factory() as session:
        with pytest.raises(PlanError) as exc:
            await PlanService(session).update(
                plan_id, PlanIn(**_data(stripe_price_month="price_dup"))
            )
        assert (exc.value.code, exc.value.status_code) == ("price_taken", 409)
        plan = await PlanService(session).get(plan_id)
        assert plan.stripe_price_month == "price_team_m"


async def test_create_key_race_over_http_is_409(app, admin, monkeypatch):
    await _precreate(app)
    _skip_all_checks(monkeypatch)
    response = await admin.post(f"{ADMIN}/plans", json=_data())
    assert (response.status_code, response.json()["detail"]) == (409, "plan_key_taken")
    again = await admin.post(f"{ADMIN}/plans", json=_data("pro"))
    assert again.status_code == 201, again.text


# ── a price someone pays on cannot change ──


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
