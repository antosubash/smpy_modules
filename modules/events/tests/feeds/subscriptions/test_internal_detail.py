"""An internal address (switch on, manager-saved) leaks as little as possible: a failure is only
"unreachable" (nothing answered) or "not a calendar" (something answered), with no status number,
no TLS or timeout distinction; the precise cause stays in the server log, without the address."""

from __future__ import annotations

import logging

import pytest
from sm_events.core.settings import EventsSettings

from tests.feeds.subscriptions.refresh_support import Fetcher, failure, load, seed, tick

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


async def test_the_schedule_still_follows_the_precise_failure(db_state):
    (sid,) = await seed(db_state, may_use_private=True)
    await tick(db_state, Fetcher(failure("gone", http_status=410)), settings=ON)
    assert (await load(db_state, sid)).status == "disabled"  # "gone" stops it, whatever is shown


async def test_a_public_or_ordinary_subscription_keeps_the_precise_code(db_state):
    (plain,) = await seed(db_state, slug="a")
    (public,) = await seed(db_state, slug="b", public=True)
    await tick(db_state, Fetcher(failure("http_status", http_status=503)), settings=ON)
    for sid in (plain, public):
        sub = await load(db_state, sid)
        assert (sub.error_code, sub.last_http_status) == ("http_status", 503)
