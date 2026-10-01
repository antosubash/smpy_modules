"""QA round 1: plan-key races (BUG-001), PlanIn bounds (BUG-007), return URL (BUG-009)."""

from __future__ import annotations

import pytest
from api_helpers import arm_csrf
from helpers import make_plan
from pydantic import ValidationError
from sm_billing.admin import connection_changes
from sm_billing.errors import BillingError
from sm_billing.plans import PlanError, PlanService
from sm_billing.schemas import ConnectionIn, PlanIn

ADMIN = "/api/billing/admin"
BIG = 2_000_000_000


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


# ── BUG-001 ─────────────────────────────────────────────────────────


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


# ── BUG-007 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "over",
    [
        {"amount_month": BIG + 1},
        {"amount_year": BIG + 1},
        {"limits": {"tenants.seats": BIG + 1}},
        {"sort_order": 1_000_001},
        {"sort_order": -1_000_001},
        {"trial_days": 731},
    ],
)
async def test_plan_bounds_rejected(admin, over):
    with pytest.raises(ValidationError):
        PlanIn(**_data(**over))
    response = await admin.post(f"{ADMIN}/plans", json=_data(**over))
    assert response.status_code == 422, response.text


def test_plan_bounds_inclusive():
    plan = PlanIn(
        **_data(
            amount_month=BIG,
            amount_year=BIG,
            limits={"tenants.seats": BIG},
            sort_order=-1_000_000,
            trial_days=730,
        )
    )
    assert plan.amount_month == BIG
    assert PlanIn(**_data(sort_order=1_000_000)).sort_order == 1_000_000


# ── BUG-009 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("", ""),
        ("   ", ""),
        ("https://app.example.com", "https://app.example.com"),
        ("https://app.example.com/", "https://app.example.com"),
        (" http://localhost:8000/ ", "http://localhost:8000"),
    ],
)
def test_return_url_accepted(raw, stored):
    assert connection_changes(ConnectionIn(return_base_url=raw))["return_base_url"] == stored


@pytest.mark.parametrize(
    "raw",
    [
        "not a url",
        "javascript:alert(1)",
        "ftp://example.com",
        "https://",
        "https://app.example.com/billing",
        "https://app.example.com/?x=1",
        "https://app.example.com/#top",
        "https://user:pw@app.example.com",
        "https://app example.com",
        "https://a.example.com/" + "x" * 300,
        "https://" + "a" * 250 + ".com",
        # urlsplit silently drops these, so they must be refused before parsing.
        "https://exa\nmple.com",
        "https://exa\tmple.com",
        "https://example.com\x00",
    ],
)
def test_return_url_rejected(raw):
    with pytest.raises(BillingError) as exc:
        connection_changes(ConnectionIn(return_base_url=raw))
    assert (exc.value.code, exc.value.status_code) == ("invalid_return_url", 400)
    assert "http" in exc.value.extra["message"]


@pytest.mark.parametrize("raw", ["not a url", "javascript:alert(1)", "https://x.io/" + "a" * 300])
async def test_return_url_rejected_over_http(app, admin, raw):
    response = await admin.put(f"{ADMIN}/connection", json={"return_base_url": raw})
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "invalid_return_url"
    assert response.json()["message"]
    assert app.state.sm_billing.settings.return_base_url == ""
