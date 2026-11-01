"""The admin Subscriptions screen pages its list, in both subject modes (#283)."""

from __future__ import annotations

from api_helpers import page_props
from conftest import make_user
from helpers import make_plan, make_sub, make_tenant, make_users
from sm_billing import constants as c
from sm_billing import subscription_list
from sm_billing.models import Subscription
from sm_billing.subjects import subject_for_user

SCREEN = "/admin/billing/subscriptions"


async def _seed_tenants(app, n: int) -> None:
    async with app.state.sm.db.session_factory() as session:
        for i in range(n):
            await make_tenant(session, f"org-{i:03}")
        await session.commit()


async def _counts(app, **filters) -> tuple[int, int]:
    async with app.state.sm.db.session_factory() as session:
        total = await subscription_list.subscription_count(session, app, **filters)
        rows = await subscription_list.subscription_rows(session, app, limit=10_000, **filters)
    return total, len(rows)


async def test_count_matches_rows_in_tenant_mode(app):
    await _seed_tenants(app, 7)
    assert await _counts(app) == (7, 7)
    assert await _counts(app, q="org-00") == (7, 7)
    assert await _counts(app, q="org-003") == (1, 1)
    assert await _counts(app, q="nothing-like-this") == (0, 0)
    assert await _counts(app, status="active") == (0, 0)  # none has a subscription


async def test_count_matches_rows_in_user_mode(user_mode_app):
    app = user_mode_app
    await make_users(app, 7)
    total, rows = await _counts(app)
    assert total == rows >= 7
    assert await _counts(app, q="u00") == (7, 7)
    assert await _counts(app, q="u003") == (1, 1)
    assert await _counts(app, q="  u003  ") == (1, 1)  # trimmed like the rows
    assert await _counts(app, status="active") == (0, 0)


async def _assert_two_pages(client) -> None:
    first = (await page_props(client, SCREEN))["subscriptions"]
    assert (first["page"], first["per_page"], len(first["items"])) == (1, 50, 50)
    assert first["pages"] == 2 and first["total"] >= 53
    second = (await page_props(client, f"{SCREEN}?page=2"))["subscriptions"]
    assert second["page"] == 2 and len(second["items"]) == first["total"] - 50
    ids = {r["tenant_id"] for r in first["items"]} | {r["tenant_id"] for r in second["items"]}
    assert len(ids) == first["total"]  # no row twice, none missed


async def test_screen_serves_fifty_then_the_rest_for_tenants(app, admin):
    await _seed_tenants(app, c.ADMIN_PAGE_SIZE + 3)
    await _assert_two_pages(admin)


async def test_screen_serves_fifty_then_the_rest_for_users(user_mode_app, admin):
    await make_users(user_mode_app, c.ADMIN_PAGE_SIZE + 3)
    await _assert_two_pages(admin)


async def test_page_is_clamped_and_forgiving(user_mode_app, admin):
    await make_users(user_mode_app, c.ADMIN_PAGE_SIZE + 3)
    last = (await page_props(admin, f"{SCREEN}?page=999"))["subscriptions"]
    assert last["page"] == last["pages"] == 2
    for bad in ("abc", "0", "-4", ""):
        got = (await page_props(admin, f"{SCREEN}?page={bad}"))["subscriptions"]
        assert got["page"] == 1, bad


async def test_filters_apply_across_pages(user_mode_app, admin):
    await make_users(user_mode_app, c.ADMIN_PAGE_SIZE + 3)
    props = await page_props(admin, f"{SCREEN}?q=u0&page=2")
    page = props["subscriptions"]
    assert page["total"] == 53 and page["page"] == 2 and len(page["items"]) == 3
    assert props["search"] == "u0"


async def test_status_filter_counts_a_real_subscription_in_tenant_mode(app):
    await _seed_tenants(app, 3)
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, "team")
        await make_sub(session, await make_tenant(session, "paying"), plan, status="active")
        await session.commit()
    assert await _counts(app, status="active") == (1, 1)
    assert await _counts(app, status="canceled") == (0, 0)
    assert (await _counts(app))[0] == 4


async def test_status_filter_counts_a_real_subscription_in_user_mode(user_mode_app):
    app = user_mode_app
    await make_users(app, 3)
    user_id = await make_user(app, "paying@x.io")
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, "team")
        subject = subject_for_user(user_id)
        session.add(Subscription(tenant_id=subject, plan_id=plan.id, status="active"))
        await session.commit()
    assert await _counts(app, status="active") == (1, 1)
    assert await _counts(app, status="active", q="paying") == (1, 1)
    assert await _counts(app, status="active", q="u00") == (0, 0)


async def test_exactly_one_full_page_is_one_page_and_one_more_is_two(app, admin):
    await _seed_tenants(app, c.ADMIN_PAGE_SIZE)
    full = (await page_props(admin, SCREEN))["subscriptions"]
    assert (full["total"], full["pages"], len(full["items"])) == (50, 1, 50)
    async with app.state.sm.db.session_factory() as session:
        await make_tenant(session, "org-extra")
        await session.commit()
    more = (await page_props(admin, SCREEN))["subscriptions"]
    assert (more["total"], more["pages"], len(more["items"])) == (51, 2, 50)


async def test_an_over_long_search_is_truncated_not_rejected(admin):
    long = "x" * (c.ADMIN_SEARCH_MAX + 30)
    props = await page_props(admin, f"{SCREEN}?q={long}")
    assert props["search"] == "x" * c.ADMIN_SEARCH_MAX
    assert props["subscriptions"]["total"] == 0
