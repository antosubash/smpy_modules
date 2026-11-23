"""The address policy is asked again at every fetch, with the real fetcher and a fake resolver."""

from __future__ import annotations

import pytest

from tests.feeds.subscriptions.refresh_support import load, seed, tick
from tests.support.net import resolver  # noqa: F401

pytestmark = pytest.mark.unbound_tenant


async def test_policy_rechecked_at_fetch(db_state, resolver):  # noqa: F811
    (sid,) = await seed(db_state, url="https://cal.example/feed.ics")
    resolver["cal.example"] = ["10.0.0.5"]  # public when it was saved, private now
    from sm_events.feeds.subscriptions import fetch

    got = await tick(db_state, fetch.fetch_feed)
    assert got["failed"] == 1
    sub = await load(db_state, sid)
    assert (sub.status, sub.error_code) == ("error", "url_unreachable")


async def test_switch_turned_off_after_save_refuses_an_intranet_address(db_state):
    (sid,) = await seed(db_state, url="http://intranet.example/feed.ics")
    from sm_events.feeds.subscriptions import fetch

    await tick(db_state, fetch.fetch_feed)
    assert (await load(db_state, sid)).error_code == "url_scheme"
