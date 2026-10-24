"""The usage card (``GET /api/billing/usage``, the billing page) and the admin
usage reads (overview, ledger, holds) — permissions and tenant isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from api_helpers import arm_csrf, create_tenant, page_props
from sm_billing.metering.periods import calendar_month
from sm_billing.models import UsagePeriod
from usage_api_helpers import (
    ADMIN,
    BYTES,
    COUNTER,
    GAUGE,
    consume,
    define_meters,
    put_on_plan,
    reserve,
)


@pytest.fixture(autouse=True)
def _meters(app):
    define_meters(app)


@pytest.fixture
async def admin(authenticated_client):
    await arm_csrf(authenticated_client, "/admin/billing/usage")
    return authenticated_client


async def test_card_lists_limited_and_used_meters(app, user_client):
    async with user_client("owner@x.io") as (owner, _):
        tenant = (await create_tenant(owner))["id"]
        await put_on_plan(app, tenant, {COUNTER: 10, GAUGE: 2})
        await consume(app, tenant, 3)
        await reserve(app, tenant)
        rows = (await owner.get("/api/billing/usage")).json()
    by_meter = {r["meter"]: r for r in rows}
    # BYTES: registered, but neither limited nor used, so not on the card.
    assert set(by_meter) == {COUNTER, GAUGE}
    counter, gauge = by_meter[COUNTER], by_meter[GAUGE]
    assert (counter["used"], counter["limit"], counter["kind"]) == (3, 10, "counter")
    assert counter["label_key"] == "demo.meters.exports"
    assert counter["period_end"] is not None and counter["holds"] is None
    assert (gauge["used"], gauge["limit"], gauge["holds"]) == (1, 2, 1)
    assert gauge["period_end"] is None


async def test_unlimited_meter_shows_once_used(app, user_client):
    async with user_client("owner@x.io") as (owner, _):
        tenant = (await create_tenant(owner))["id"]
        assert (await owner.get("/api/billing/usage")).json() == []
        await reserve(app, tenant, 2048, meter=BYTES)
        rows = (await owner.get("/api/billing/usage")).json()
    assert [(r["meter"], r["used"], r["limit"], r["unit"]) for r in rows] == [
        (BYTES, 2048, None, "bytes")
    ]


async def test_card_is_per_tenant_and_on_the_page(app, user_client):
    async with user_client("a@x.io") as (a, _), user_client("b@x.io") as (b, _):
        ta = (await create_tenant(a, "A"))["id"]
        tb = (await create_tenant(b, "B"))["id"]
        for tenant in (ta, tb):
            await put_on_plan(app, tenant, {COUNTER: 5})
        await consume(app, ta, 4)
        assert [r["used"] for r in (await b.get("/api/billing/usage")).json()] == [0]
        props = await page_props(a, "/billing/")
    assert [(r["meter"], r["used"], r["limit"]) for r in props["usage"]] == [(COUNTER, 4, 5)]


async def test_card_needs_a_tenant(user_client):
    async with user_client("lonely@x.io") as (client, _):
        response = await client.get("/api/billing/usage")
    assert (response.status_code, response.json()["detail"]) == (403, "tenant_required")


async def test_admin_overview_filters_and_pages(app, admin, user_client):
    async with user_client("a@x.io") as (a, _), user_client("b@x.io") as (b, _):
        ta = (await create_tenant(a, "Alpha"))["id"]
        tb = (await create_tenant(b, "Beta"))["id"]
    await put_on_plan(app, ta, {COUNTER: 10, GAUGE: 1})
    await consume(app, ta, 9)
    await reserve(app, ta)
    await consume(app, tb, 1)  # default plan: unlimited

    page = (await admin.get(ADMIN)).json()
    rows = [(r["tenant_name"], r["meter"], r["used"], r["percent"]) for r in page["items"]]
    # Fullest first; unlimited (no percent) last.
    assert rows == [
        ("Alpha", GAUGE, 1, 100.0),
        ("Alpha", COUNTER, 9, 90.0),
        ("Beta", COUNTER, 1, None),
    ]
    assert page["total"] == 3 and page["pages"] == 1

    over = (await admin.get(ADMIN, params={"over": "true", "meter": COUNTER})).json()
    assert [(r["tenant_name"], r["meter"]) for r in over["items"]] == [("Alpha", COUNTER)]
    beta = (await admin.get(ADMIN, params={"q": "bet"})).json()
    assert [r["tenant_id"] for r in beta["items"]] == [tb]
    paged = (await admin.get(ADMIN, params={"per_page": 2, "page": 9})).json()
    assert (paged["page"], paged["pages"], len(paged["items"])) == (2, 2, 1)
    previous = (await admin.get(ADMIN, params={"period": "previous"})).json()
    assert previous["items"] == []


async def test_admin_page_renders(app, admin):
    props = await page_props(admin, "/admin/billing/usage?over=1&meter=x")
    assert props["usage"]["items"] == []
    assert props["filters"] == {"meter": "x", "q": "", "over": True, "period": "current"}
    assert [m["key"] for m in props["meters"]] == [COUNTER, GAUGE, BYTES]
    assert props["can_manage"] is True


async def test_admin_ledger_and_holds_are_per_tenant(app, admin, user_client):
    async with user_client("a@x.io") as (a, _), user_client("b@x.io") as (b, _):
        ta = (await create_tenant(a, "Alpha"))["id"]
        tb = (await create_tenant(b, "Beta"))["id"]
    for _ in range(3):
        await consume(app, ta, 1)
    await consume(app, tb, 1)
    hold = await reserve(app, ta)
    await reserve(app, tb)

    first = (await admin.get(f"{ADMIN}/{ta}/events", params={"per_page": 2})).json()
    assert (first["total"], first["pages"], len(first["items"])) == (3, 2, 2)
    assert {e["kind"] for e in first["items"]} == {"consume"}
    assert first["items"][0]["id"] > first["items"][1]["id"]  # newest first
    none = (await admin.get(f"{ADMIN}/{ta}/events", params={"kind": "adjust"})).json()
    assert none["total"] == 0
    holds = (await admin.get(f"{ADMIN}/{ta}/holds")).json()
    assert [(h["id"], h["status"]) for h in holds] == [(hold.id, "held")]
    released = (await admin.get(f"{ADMIN}/{ta}/holds", params={"status": "released"})).json()
    assert released == []


async def test_admin_reads_need_platform_view(app, user_client):
    async with user_client("owner@x.io") as (owner, _):
        tenant = (await create_tenant(owner))["id"]
        for url in (ADMIN, f"{ADMIN}/{tenant}/events", f"{ADMIN}/{tenant}/holds"):
            assert (await owner.get(url)).status_code == 403, url
        assert (await owner.get("/admin/billing/usage")).status_code == 403


async def test_admin_rejects_bad_query(admin):
    assert (await admin.get(f"{ADMIN}/{'x' * 33}/events")).status_code == 422
    assert (await admin.get(f"{ADMIN}/t/events", params={"kind": "nope"})).status_code == 422
    assert (await admin.get(ADMIN, params={"period": "last"})).status_code == 422


async def test_previous_period_and_stale_rows(app, admin, user_client):
    async with user_client("a@x.io") as (a, _):
        tenant = (await create_tenant(a, "Alpha"))["id"]
        start, end = calendar_month(datetime.now(UTC))
        last_start, _ = calendar_month(start - timedelta(days=1))
        async with app.state.sm.db.session_factory() as session:
            # Last month's counter, and a row from a provider anchor since dropped
            # whose period still contains "now": neither is the current period.
            session.add(
                UsagePeriod(
                    tenant_id=tenant,
                    meter=COUNTER,
                    period_start=last_start,
                    period_end=start,
                    used=7,
                )
            )
            session.add(
                UsagePeriod(
                    tenant_id=tenant,
                    meter=COUNTER,
                    period_start=start + timedelta(hours=1),
                    period_end=end + timedelta(days=3),
                    used=99,
                )
            )
            await session.commit()
        assert (await admin.get(ADMIN)).json()["items"] == []
        previous = (await admin.get(ADMIN, params={"period": "previous"})).json()
        assert [(r["used"], r["period_end"][:10]) for r in previous["items"]] == [
            (7, start.date().isoformat())
        ]
        assert (await a.get("/api/billing/usage")).json() == []
