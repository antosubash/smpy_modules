"""One pass of the beat: claim, fetch with no session open, store fenced, schedule."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_events.core.settings import EventsSettings

from tests.feeds.subscriptions.refresh_support import (
    FEED,
    NOW,
    Fetcher,
    failure,
    load,
    not_modified,
    ok,
    seed,
    tick,
    titles,
)

pytestmark = pytest.mark.unbound_tenant


async def test_due_rows_fetched_and_stored(db_state):
    (sid,) = await seed(db_state)
    fetcher = Fetcher()
    got = await tick(db_state, fetcher)
    assert (got["fetched"], got["failed"], got["tenants"]) == (1, 0, 1)
    sub = await load(db_state, sid)
    assert (sub.status, sub.error_code, sub.generation, sub.item_count) == ("ok", None, 1, 2)
    assert (sub.etag, sub.consecutive_failures, sub.lease_owner) == ('"v1"', 0, None)
    assert sub.last_ok_at == NOW and sub.last_fetched_at == NOW
    assert sub.next_fetch_at > NOW + timedelta(minutes=50)
    assert await titles(db_state, sid) == ["Alpha", "Beta"]
    assert fetcher.calls[0]["url"] == "https://default-team-0.example/feed.ics"


async def test_conditional_validators_are_sent_back(db_state):
    (sid,) = await seed(db_state, etag='"v1"', last_modified="Wed, 01 Jul 2026 10:00:00 GMT")
    fetcher = Fetcher(not_modified())
    await tick(db_state, fetcher)
    call = fetcher.calls[0]
    assert (call["etag"], call["last_modified"]) == ('"v1"', "Wed, 01 Jul 2026 10:00:00 GMT")
    assert call["max_bytes"] == EventsSettings().import_max_bytes
    assert call["policy"].allow_private is False and sid


async def test_not_modified_touches_no_item(db_state):
    (sid,) = await seed(db_state)
    await tick(db_state, Fetcher())
    before = await load(db_state, sid)
    later = NOW + timedelta(hours=2)
    got = await tick(db_state, Fetcher(not_modified()), now=later)
    assert got["not_modified"] == 1
    sub = await load(db_state, sid)
    assert (sub.generation, sub.item_count, sub.etag) == (1, 2, before.etag)
    assert sub.last_ok_at == later and sub.consecutive_failures == 0 and sub.status == "ok"
    assert sub.next_fetch_at > later
    assert await titles(db_state, sid) == ["Alpha", "Beta"]


@pytest.mark.parametrize(
    "error",
    [
        failure("timeout"),
        failure("http_status", http_status=500),
        failure("too_large"),
        failure("ics_invalid"),
    ],
    ids=["timeout", "http_500", "too_large", "ics_invalid"],
)
async def test_failure_keeps_items(db_state, error):
    (sid,) = await seed(db_state)
    await tick(db_state, Fetcher())
    later = NOW + timedelta(hours=2)
    got = await tick(db_state, Fetcher(error), now=later)
    assert got["failed"] == 1
    sub = await load(db_state, sid)
    assert (sub.status, sub.error_code, sub.consecutive_failures) == ("error", error.code, 1)
    assert sub.last_http_status == error.http_status
    assert (sub.generation, sub.item_count) == (1, 2)
    assert await titles(db_state, sid) == ["Alpha", "Beta"]
    assert later + timedelta(minutes=50) <= sub.next_fetch_at <= later + timedelta(minutes=70)


async def test_a_body_that_fails_the_scanner_keeps_items_and_records_the_code(db_state):
    (sid,) = await seed(db_state)
    await tick(db_state, Fetcher())
    broken = ok(FEED.replace(b"Alpha", b"Al\x00pha"))
    await tick(db_state, Fetcher(broken), now=NOW + timedelta(hours=2))
    sub = await load(db_state, sid)
    assert (sub.status, sub.error_code, sub.generation) == ("error", "ics_invalid", 1)
    assert await titles(db_state, sid) == ["Alpha", "Beta"]


async def test_disabled_after_ten_failures_shows_reason(db_state):
    (sid,) = await seed(db_state, consecutive_failures=9, status="error", error_code="timeout")
    await tick(db_state, Fetcher(failure("timeout")))
    sub = await load(db_state, sid)
    assert (sub.status, sub.error_code, sub.consecutive_failures) == ("disabled", "timeout", 10)
    fetcher = Fetcher()
    assert (await tick(db_state, fetcher, now=NOW + timedelta(days=3)))["tenants"] == 0
    assert fetcher.calls == []  # a disabled subscription is never picked


async def test_gone_disables_at_once(db_state):
    (sid,) = await seed(db_state)
    await tick(db_state, Fetcher(failure("gone", http_status=410)))
    assert (await load(db_state, sid)).status == "disabled"


async def test_unreadable_url_disables_without_fetch(db_state):
    (sid,) = await seed(db_state)
    from sm_events.core.tenancy import tenant_scope
    from sm_events.models import Subscription
    from sqlalchemy import update

    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            await db.execute(update(Subscription).values(url_enc="enc:v2:garbage"))
            await db.commit()
    fetcher = Fetcher()
    await tick(db_state, fetcher)
    sub = await load(db_state, sid)
    assert (sub.status, sub.error_code) == ("disabled", "url_unreadable")
    assert fetcher.calls == []


async def test_an_unexpected_fetcher_exception_is_internal_and_leaks_nothing(db_state, caplog):
    (sid,) = await seed(db_state)
    with caplog.at_level("DEBUG"):
        await tick(db_state, Fetcher(RuntimeError("secret-TOKEN https://x.example/p")))
    sub = await load(db_state, sid)
    assert (sub.status, sub.error_code) == ("error", "internal")
    assert "TOKEN" not in caplog.text and "x.example" not in caplog.text


async def test_trashed_calendar_not_fetched(db_state):
    from sm_events.core.tenancy import tenant_scope
    from sm_events.models import Calendar
    from sqlalchemy import update

    await seed(db_state)
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            await db.execute(update(Calendar).values(is_deleted=True))
            await db.commit()
    fetcher = Fetcher()
    await tick(db_state, fetcher)
    assert fetcher.calls == []


async def test_a_retry_after_pushes_the_next_fetch_out(db_state):
    (sid,) = await seed(db_state)
    await tick(db_state, Fetcher(failure("http_status", http_status=503, retry_after=5 * 3600)))
    assert (await load(db_state, sid)).next_fetch_at >= NOW + timedelta(hours=5)


async def test_a_max_age_pushes_the_next_fetch_out(db_state):
    (sid,) = await seed(db_state)
    await tick(db_state, Fetcher(ok(max_age=6 * 3600)))
    assert (await load(db_state, sid)).next_fetch_at >= NOW + timedelta(hours=6)


async def test_the_subscriptions_own_interval_wins(db_state):
    (sid,) = await seed(db_state, refresh_minutes=1440)
    await tick(db_state, Fetcher())
    assert (await load(db_state, sid)).next_fetch_at >= NOW + timedelta(hours=21)
