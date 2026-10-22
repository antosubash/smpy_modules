"""``PlanIn`` bounds guard writes, never reads."""

from __future__ import annotations

import pytest
from api_helpers import arm_csrf
from helpers import make_plan
from pydantic import ValidationError
from sm_billing.schemas import MAX_AMOUNT, PlanIn

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


# ── PlanIn bounds ─────────────────────────────────────────────────────────


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


async def test_legacy_out_of_range_plan_still_lists(app, admin):
    """Bounds guard writes, never reads: a row stored before them must not 500 the admin.

    Above ``MAX_AMOUNT`` but inside the column: ``amount_month`` is an
    ``INTEGER``, which Postgres holds to 32 bits where SQLite would store
    anything, so a larger "legacy" value is a row no Postgres host can have.
    """
    over_bound = MAX_AMOUNT + 100_000_000
    assert over_bound < 2**31
    async with app.state.sm.db.session_factory() as session:
        await make_plan(
            session, "legacy", amount_month=over_bound, limits={"tenants.seats": 10**20}
        )
        await session.commit()
    response = await admin.get(f"{ADMIN}/plans")
    assert response.status_code == 200, response.text
    legacy = next(p for p in response.json() if p["key"] == "legacy")
    assert legacy["amount_month"] == over_bound
    page = await admin.get("/admin/billing/plans", headers={"X-Inertia": "true"})
    assert page.status_code == 200
