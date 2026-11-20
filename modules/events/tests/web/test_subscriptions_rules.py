"""What a subscription may be and do: limits, duplicates, flags, the intranet switch, refresh."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.tenancy import tenant_scope
from sm_events.models import ExternalItem, Subscription
from sqlalchemy import select, update

from tests.support.calendars import BASE, MANAGER, OWNER, OWNER_P
from tests.support.subscriptions import seed_item
from tests.support.subscriptions_http import (
    REAL_LAUNCH,
    SUBS,
    URL,
    add,
    app_client,
    calendar,
    row,
    stub_launch,
)


@pytest.fixture(autouse=True)
def _no_launch(monkeypatch):
    return stub_launch(monkeypatch)


@pytest.fixture
async def http():
    async with app_client() as client:
        yield client


async def test_create_seals_masks_and_is_due_now(http):
    cid = await calendar(http)
    made = (await add(http, cid, OWNER)).json()
    sub = await row(http, made["id"])
    assert sub.url_enc.startswith("enc:v2:") and "SECRET" not in sub.url_enc
    assert (sub.url_display, sub.status, sub.created_by) == (
        "https://feeds.example.test/…",
        "pending",
        "o",
    )
    assert sub.next_fetch_at is not None and sub.next_fetch_at <= utcnow()
    assert made["effective_refresh_minutes"] == 60 and made["item_count"] == 0


async def test_duplicate_url_conflicts_even_after_normalisation(http):
    cid = await calendar(http)
    assert (await add(http, cid, OWNER, url="https://a.example.test/x.ics")).status_code == 201
    for url in ("webcal://A.example.test/x.ics#frag", "https://a.example.test:443/x.ics"):
        got = await add(http, cid, OWNER, url=url)
        assert (got.status_code, got.json()["code"]) == (409, "subscription_exists")
    other = await calendar(http)
    assert (await add(http, other, OWNER, url="https://a.example.test/x.ics")).status_code == 201


async def test_limits_per_calendar_and_per_tenant(http, monkeypatch):
    cid = await calendar(http)
    for n in range(constants.SUBSCRIPTIONS_PER_CALENDAR):
        assert (
            await add(http, cid, OWNER, url=f"https://h{n}.example.test/x.ics")
        ).status_code == 201
    got = await add(http, cid, OWNER, url="https://extra.example.test/x.ics")
    assert (got.status_code, got.json()["code"]) == (409, "subscription_limit")
    monkeypatch.setattr(constants, "SUBSCRIPTIONS_PER_TENANT", 11)
    other = await calendar(http)
    assert (await add(http, other, OWNER, url="https://t1.example.test/x.ics")).status_code == 201
    over = await add(http, other, OWNER, url="https://t2.example.test/x.ics")
    assert (over.status_code, over.json()["code"]) == (409, "subscription_limit")


async def test_public_flag_needs_publish_and_a_public_calendar(http):
    pub = await calendar(http, OWNER_P, visibility="public")
    private = await calendar(http)
    denied = await add(http, pub, OWNER, public=True)
    assert (denied.status_code, denied.json()["code"]) == (403, "publish_required")
    assert (await add(http, pub, OWNER_P, public=True)).status_code == 201
    wrong = await add(http, private, OWNER_P, url="https://b.example.test/x.ics", public=True)
    assert (wrong.status_code, wrong.json()["code"]) == (422, "subscription_not_public_calendar")


async def test_intranet_address_needs_the_switch_and_the_manager():
    cases = [(True, MANAGER, 201), (True, OWNER, 422), (False, MANAGER, 422)]
    for switch, who, status in cases:
        async with app_client(allow_private_subscription_urls=switch) as client:
            cid = await calendar(client)
            got = await add(client, cid, who, url="http://10.0.0.5:8080/feed.ics")
            assert got.status_code == status, (switch, got.text)
            if status == 422:
                assert got.json()["code"] in {"url_scheme", "url_port", "url_unreachable"}


async def test_url_change_clears_validators_and_is_due(http):
    cid = await calendar(http)
    sid = (await add(http, cid, OWNER)).json()["id"]
    async with http.db_state.session_factory() as db:
        await db.execute(
            update(Subscription).values(
                etag='"v1"', last_modified="x", status="error", error_code="timeout",
                consecutive_failures=4, next_fetch_at=utcnow() + timedelta(days=1),
            )
        )  # fmt: skip
        await db.commit()
    got = await http.patch(
        f"{SUBS}/{sid}", json={"url": "https://new.example.test/a.ics"}, headers=OWNER
    )
    assert got.status_code == 200 and got.json()["status"] == "pending"
    sub = await row(http, sid)
    assert (sub.etag, sub.last_modified, sub.error_code, sub.consecutive_failures) == (
        None,
        None,
        None,
        0,
    )
    assert sub.next_fetch_at <= utcnow() and sub.url_display == "https://new.example.test/…"
    same = await http.patch(
        f"{SUBS}/{sid}", json={"url": "https://new.example.test/a.ics"}, headers=OWNER
    )
    assert same.status_code == 200


async def test_patch_clears_colour_and_interval_with_null_and_checks_bounds(http):
    cid = await calendar(http)
    sid = (await add(http, cid, OWNER, color="#112233", refresh_minutes=30)).json()["id"]
    got = await http.patch(
        f"{SUBS}/{sid}", json={"color": None, "refresh_minutes": None}, headers=OWNER
    )
    assert (got.json()["color"], got.json()["refresh_minutes"]) == (None, None)
    for bad in (
        {"refresh_minutes": 5},
        {"refresh_minutes": 2000},
        {"color": "red"},
        {"label": ""},
        {"label": "a\nb"},
    ):
        assert (await http.patch(f"{SUBS}/{sid}", json=bad, headers=OWNER)).status_code == 422


async def test_a_stale_edit_is_refused(http):
    cid = await calendar(http)
    made = (await add(http, cid, OWNER)).json()
    first = await http.patch(
        f"{SUBS}/{made['id']}", json={"label": "A", "expected": made["version"]}, headers=OWNER
    )
    assert first.status_code == 200
    second = await http.patch(
        f"{SUBS}/{made['id']}", json={"label": "B", "expected": made["version"]}, headers=OWNER
    )
    assert (second.status_code, second.json()["code"]) == (409, "stale")


async def test_pause_and_resume(http):
    cid = await calendar(http)
    sid = (await add(http, cid, OWNER)).json()["id"]
    assert (await http.post(f"{SUBS}/{sid}/pause", headers=OWNER)).json()["status"] == "paused"
    async with http.db_state.session_factory() as db:
        await db.execute(
            update(Subscription).values(
                consecutive_failures=7,
                error_code="timeout",
                updated_at=utcnow() - timedelta(hours=1),
            )
        )
        await db.commit()
    resumed = (await http.post(f"{SUBS}/{sid}/resume", headers=OWNER)).json()
    assert (
        resumed["status"] == "pending"
        and resumed["consecutive_failures"] == 0
        and resumed["error_code"] is None
    )


async def test_refresh_too_soon_and_while_leased(http):
    cid = await calendar(http)
    sid = (await add(http, cid, OWNER)).json()["id"]
    first = await http.post(f"{SUBS}/{sid}/refresh", headers=OWNER)
    assert first.status_code == 202
    async with http.db_state.session_factory() as db:
        await db.execute(
            update(Subscription).values(last_fetched_at=utcnow() - timedelta(seconds=100))
        )
        await db.commit()
    soon = await http.post(f"{SUBS}/{sid}/refresh", headers=OWNER)
    assert (soon.status_code, soon.json()["code"]) == (429, "refresh_too_soon")
    assert 190 <= int(soon.headers["retry-after"]) <= 200
    async with http.db_state.session_factory() as db:
        await db.execute(
            update(Subscription).values(
                last_fetched_at=None, lease_owner="w", lease_until=utcnow() + timedelta(minutes=1)
            )
        )
        await db.commit()
    assert (await http.post(f"{SUBS}/{sid}/refresh", headers=OWNER)).status_code == 429


async def test_delete_wipes_the_ciphertext_and_the_items(http):
    cid = await calendar(http)
    sid = (await add(http, cid, OWNER)).json()["id"]
    async with http.db_state.session_factory() as db:
        sub = await row(http, sid)
        with tenant_scope("default"):
            await seed_item(db, sub, "a", utc_now(), title="x")
        await db.commit()
    assert (await http.delete(f"{SUBS}/{sid}", headers=OWNER)).status_code == 204
    gone = await row(http, sid, include_deleted=True)
    assert (gone.url_enc, gone.is_deleted) == ("", True)
    async with http.db_state.session_factory() as db:
        assert (await db.execute(select(ExternalItem))).scalars().all() == []
    assert (await http.get(f"{BASE}/{cid}/subscriptions", headers=OWNER)).json() == []


def utc_now():
    return utcnow()


async def test_the_list_shows_status_for_managers_without_secrets(http):
    cid = await calendar(http)
    await add(http, cid, OWNER)
    (item,) = (await http.get(f"{BASE}/{cid}/subscriptions", headers=OWNER)).json()
    assert set(item) == {
        "id", "calendar_id", "url_display", "label", "color", "refresh_minutes",
        "effective_refresh_minutes", "public", "status", "error_code", "last_http_status",
        "last_fetched_at", "last_ok_at", "next_fetch_at", "consecutive_failures", "item_count",
        "last_counts", "may_use_internal_addresses", "version",
    }  # fmt: skip
    assert URL not in str(item)


async def test_create_triggers_the_first_fetch_when_celery_is_eager(http, monkeypatch):
    from sm_events.feeds.subscriptions import launch, refresh

    from tests.feeds.subscriptions.refresh_support import FEED, Fetcher, ok

    fetcher = Fetcher(ok(FEED))
    monkeypatch.setattr(launch, "refresh_one", REAL_LAUNCH)
    monkeypatch.setattr(launch, "celery_eager", lambda: True)
    monkeypatch.setattr(refresh, "fetch_feed", fetcher)
    cid = await calendar(http)
    made = await add(http, cid, OWNER)
    assert made.status_code == 201 and len(fetcher.calls) == 1
    shown = (await http.get(f"{BASE}/{cid}/subscriptions", headers=OWNER)).json()[0]
    assert (shown["status"], shown["item_count"]) == ("ok", 2)
    assert shown["last_ok_at"] is not None
    assert fetcher.calls[0]["policy"].intranet is False
