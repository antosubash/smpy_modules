"""The admin overview's current and previous period follow the same period
resolution enforcement does — not the rollup rows' stored boundaries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from api_helpers import arm_csrf, create_tenant
from helpers import make_plan
from sm_billing.metering.periods import calendar_month, previous_period
from sm_billing.models import Subscription, UsagePeriod
from usage_api_helpers import ADMIN, COUNTER, define_meters

OTHER = "other.counter"
NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _meters(app):
    define_meters(app)
    app.state.billing_meters.define(key=OTHER, kind="counter")


@pytest.fixture
async def admin(authenticated_client):
    await arm_csrf(authenticated_client, "/admin/billing/usage")
    return authenticated_client


def _sub(start, end, interval="month") -> Subscription:
    return Subscription(
        tenant_id="t",
        plan_id=1,
        interval=interval,
        current_period_start=start,
        current_period_end=end,
    )


def test_previous_of_the_calendar_fallback_is_last_month():
    current = calendar_month(NOW)
    assert previous_period(None, NOW) == (datetime(2026, 9, 1, tzinfo=UTC), current[0])


@pytest.mark.parametrize(
    ("start", "interval", "expected"),
    [
        (datetime(2026, 10, 15, 9, tzinfo=UTC), "month", datetime(2026, 9, 15, 9, tzinfo=UTC)),
        (datetime(2027, 3, 31, tzinfo=UTC), "month", datetime(2027, 2, 28, tzinfo=UTC)),
        (datetime(2026, 1, 15, tzinfo=UTC), "month", datetime(2025, 12, 15, tzinfo=UTC)),
        (datetime(2026, 6, 1, tzinfo=UTC), "year", datetime(2025, 6, 1, tzinfo=UTC)),
    ],
)
def test_previous_of_a_provider_period_is_one_interval_back(start, interval, expected):
    current = (start, start + timedelta(days=30))
    now = start + timedelta(days=1)
    assert previous_period(_sub(*current, interval), now) == (expected, start)


async def _tenant(app, user_client, name: str, **sub) -> str:
    async with user_client(f"{name.lower()}@x.io") as (client, _):
        tenant = (await create_tenant(client, name))["id"]
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, f"p-{name.lower()}", limits={COUNTER: 10})
        session.add(Subscription(tenant_id=tenant, plan_id=plan.id, **sub))
        await session.commit()
    return tenant


async def _rows(app, tenant: str, *rows: tuple) -> None:
    async with app.state.sm.db.session_factory() as session:
        for meter, start, end, used in rows:
            session.add(
                UsagePeriod(
                    tenant_id=tenant, meter=meter, period_start=start, period_end=end, used=used
                )
            )
        await session.commit()


async def test_an_extended_period_still_shows_its_usage(app, admin, user_client):
    """The provider moved the end out (same start): enforcement keeps counting
    into the row keyed by that start, whose stored end is now in the past."""
    now = datetime.now(UTC)
    start, end = now - timedelta(days=30), now + timedelta(days=10)
    tenant = await _tenant(
        app, user_client, "Extended", current_period_start=start, current_period_end=end
    )
    await _rows(app, tenant, (COUNTER, start, now - timedelta(days=1), 4))
    items = (await admin.get(ADMIN)).json()["items"]
    assert [(r["used"], r["period_end"][:16]) for r in items] == [(4, end.isoformat()[:16])]


async def test_previous_is_the_period_just_before_or_nothing(app, admin, user_client):
    """August's usage is not "previous" in October when September had none,
    and meters never mix months."""
    oct_start, _ = calendar_month(datetime.now(UTC))
    sep_start, _ = calendar_month(oct_start - timedelta(days=1))
    aug_start, _ = calendar_month(sep_start - timedelta(days=1))
    tenant = await _tenant(app, user_client, "Calendar")
    await _rows(
        app,
        tenant,
        (COUNTER, aug_start, sep_start, 5),  # two periods back
        (OTHER, sep_start, oct_start, 2),  # the previous period
    )
    items = (await admin.get(ADMIN, params={"period": "previous"})).json()["items"]
    assert [(r["meter"], r["used"]) for r in items] == [(OTHER, 2)]


async def test_previous_provider_period_matches_either_boundary(app, admin, user_client):
    now = datetime.now(UTC)
    start, end = now - timedelta(days=3), now + timedelta(days=27)
    tenant = await _tenant(
        app,
        user_client,
        "Stripe",
        interval="month",
        current_period_start=start,
        current_period_end=end,
    )
    prev_start = previous_period(_sub(start, end), now)[0]
    await _rows(
        app,
        tenant,
        # Started a few days off the computed start (a clamped anchor), but
        # ended exactly where the current period began.
        (COUNTER, prev_start - timedelta(days=3), start, 6),
        # Started exactly one interval back; its stored end went stale.
        (OTHER, prev_start, start - timedelta(days=2), 1),
    )
    items = (await admin.get(ADMIN, params={"period": "previous"})).json()["items"]
    assert sorted((r["meter"], r["used"], r["period_end"][:16]) for r in items) == [
        (COUNTER, 6, start.isoformat()[:16]),
        (OTHER, 1, start.isoformat()[:16]),
    ]
