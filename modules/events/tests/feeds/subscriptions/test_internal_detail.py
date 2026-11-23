"""An internal address (switch on, manager-saved) leaks as little as possible: a failure is only
"unreachable" (nothing answered) or "not a calendar" (something answered), with no status number,
no TLS or timeout distinction; the precise cause stays in the server log, without the address."""

from __future__ import annotations

import logging
import random
from datetime import timedelta

import pytest
from sm_events.core.settings import EventsSettings

from tests.feeds.subscriptions.refresh_support import NOW, Fetcher, failure, load, seed, tick

pytestmark = pytest.mark.unbound_tenant
ON = EventsSettings(allow_private_subscription_urls=True)
NOTHING_ANSWERED = [
    "timeout",
    "connect_failed",
    "tls_failed",
    "url_unreachable",
    "too_many_redirects",
]
SOMETHING_ANSWERED = ["http_status", "gone", "unexpected_content_type", "too_large", "ics_encoding"]


@pytest.mark.parametrize("code", NOTHING_ANSWERED)
async def test_nothing_answered_is_one_code(db_state, caplog, code):
    (sid,) = await seed(db_state, may_use_private=True)
    with caplog.at_level(logging.WARNING, logger="sm_events.feeds.subscriptions.attempt"):
        await tick(db_state, Fetcher(failure(code)), settings=ON)
    sub = await load(db_state, sid)
    assert (sub.error_code, sub.last_http_status) == ("url_unreachable", None)
    assert code in caplog.text and "example" not in caplog.text and str(sid) in caplog.text


@pytest.mark.parametrize("code", SOMETHING_ANSWERED)
async def test_something_answered_is_one_code_without_the_status(db_state, caplog, code):
    (sid,) = await seed(db_state, may_use_private=True)
    with caplog.at_level(logging.WARNING, logger="sm_events.feeds.subscriptions.attempt"):
        await tick(db_state, Fetcher(failure(code, http_status=503)), settings=ON)
    sub = await load(db_state, sid)
    assert (sub.error_code, sub.last_http_status) == ("not_a_calendar", None)
    assert code in caplog.text and "example" not in caplog.text


async def test_an_internal_failure_shows_no_status_specific_behaviour(db_state):
    """A 410, a 429 with Retry-After and a refused port look alike: same status, same schedule."""
    seen = {}
    for n, (code, kw) in enumerate(
        [
            ("gone", {"http_status": 410}),
            ("http_status", {"http_status": 429, "retry_after": 20 * 3600}),
            ("connect_failed", {}),
        ]
    ):
        (sid,) = await seed(db_state, slug=f"i{n}", may_use_private=True)
        await tick(db_state, Fetcher(failure(code, **kw)), settings=ON, rng=random.Random(7))
        sub = await load(db_state, sid)
        seen[code] = (sub.status, sub.next_fetch_at - sub.last_fetched_at)
    assert seen["gone"][0] == "error"  # a 410 does not disable an internal subscription at once
    assert len(set(seen.values())) <= 2  # not_a_calendar vs url_unreachable backoff alike
    assert seen["gone"] == seen["http_status"]  # the Retry-After is not believed


async def test_a_public_subscription_still_follows_a_servers_gone_and_retry_after(db_state):
    (gone,) = await seed(db_state, slug="g")
    await tick(db_state, Fetcher(failure("gone", http_status=410)), settings=ON)
    assert (await load(db_state, gone)).status == "disabled"
    (waits,) = await seed(db_state, slug="w")
    await tick(
        db_state,
        Fetcher(failure("http_status", http_status=429, retry_after=20 * 3600)),
        settings=ON,
        rng=random.Random(7),
    )
    sub = await load(db_state, waits)
    assert sub.next_fetch_at - sub.last_fetched_at >= timedelta(hours=20)


async def test_an_internal_subscription_shows_only_the_tick_not_when_it_finished(db_state):
    (internal,) = await seed(db_state, slug="i", may_use_private=True)
    (public,) = await seed(db_state, slug="p")
    late = NOW + timedelta(seconds=37, microseconds=123456)  # how long the fetch took would show
    await tick(db_state, Fetcher(failure("connect_failed")), settings=ON, utc_now=lambda: late)
    assert (await load(db_state, internal)).last_fetched_at == NOW.replace(second=0, microsecond=0)
    assert (await load(db_state, public)).last_fetched_at == late


async def test_a_public_or_ordinary_subscription_keeps_the_precise_code(db_state):
    (plain,) = await seed(db_state, slug="a")
    (public,) = await seed(db_state, slug="b", public=True)
    await tick(db_state, Fetcher(failure("http_status", http_status=503)), settings=ON)
    for sid in (plain, public):
        sub = await load(db_state, sid)
        assert (sub.error_code, sub.last_http_status) == ("http_status", 503)


async def test_with_the_switch_off_the_flag_changes_nothing_a_failure_shows(db_state):
    """The effective policy is the flag AND the install switch: a manager-saved subscription on a
    host with the switch off is an ordinary one."""
    (sid,) = await seed(db_state, may_use_private=True)
    await tick(db_state, Fetcher(failure("http_status", http_status=503)))  # switch off (default)
    sub = await load(db_state, sid)
    assert (sub.error_code, sub.last_http_status) == ("http_status", 503)
