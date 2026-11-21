"""A subscription is fetched under the policy its saver was allowed, at every fetch and hop."""

from __future__ import annotations

import httpx
import pytest
from sm_events.core.settings import EventsSettings
from sm_events.feeds.subscriptions import client, fetch, policy, refresh

from tests.feeds.subscriptions.refresh_support import Fetcher, load, seed, tick
from tests.support.net import PUBLIC_IP, ics, inner, resolver  # noqa: F401
from tests.support.subscriptions import vevent

pytestmark = pytest.mark.unbound_tenant
ON = EventsSettings(allow_private_subscription_urls=True)
OFF = EventsSettings(allow_private_subscription_urls=False)
URL = "https://cal.example/feed.ics"


@pytest.fixture(autouse=True)
def _hosts(resolver):  # noqa: F811
    resolver["cal.example"] = ["10.0.0.5"]  # public when saved, private at fetch time
    resolver["pub.example"] = [PUBLIC_IP]
    resolver["internal.example"] = ["10.0.0.9"]


async def _code(db_state, settings, **fields):
    (sid,) = await seed(db_state, url=URL, **fields)
    await tick(db_state, fetch.fetch_feed, settings=settings)
    sub = await load(db_state, sid)
    return sub.status, sub.error_code


async def test_switch_on_but_saver_not_a_manager_is_public_only(db_state, inner):  # noqa: F811
    seen = inner(lambda r: ics(vevent()) and httpx.Response(200))
    assert await _code(db_state, ON, may_use_private=False) == ("error", "url_unreachable")
    assert seen == []  # nothing was dialled


async def test_switch_on_and_manager_saved_is_allowed(db_state, inner):  # noqa: F811
    from tests.support.net import ics as feed

    seen = inner(lambda r: feed())
    assert await _code(db_state, ON, may_use_private=True) == ("ok", None)
    assert [r.url.host for r in seen] == ["10.0.0.5"]


@pytest.mark.parametrize("flag", [False, True])
async def test_switch_off_always_wins(db_state, flag):
    assert await _code(db_state, OFF, may_use_private=flag) == ("error", "url_unreachable")


async def test_a_redirect_to_a_private_address_is_refused_for_a_non_manager(db_state, inner):  # noqa: F811
    inner(lambda r: httpx.Response(302, headers={"location": "https://internal.example/x"}))
    (sid,) = await seed(db_state, url="https://pub.example/feed.ics", may_use_private=False)
    await tick(db_state, fetch.fetch_feed, settings=ON)
    assert (await load(db_state, sid)).error_code == "url_unreachable"


async def test_the_same_redirect_is_followed_for_a_manager(db_state, inner):  # noqa: F811
    from tests.support.net import ics as feed

    seen = inner(
        lambda r: (
            httpx.Response(302, headers={"location": "https://internal.example/x"})
            if r.headers["host"] == "pub.example"
            else feed()
        )
    )
    (sid,) = await seed(db_state, url="https://pub.example/feed.ics", may_use_private=True)
    await tick(db_state, fetch.fetch_feed, settings=ON)
    assert (await load(db_state, sid)).status == "ok"
    assert [r.url.host for r in seen] == [PUBLIC_IP, "10.0.0.9"]


async def test_every_hop_gets_the_same_policy_object(inner):  # noqa: F811
    hops = []

    def factory(pol):
        hops.append(pol)
        return client.PinnedTransport(pol)

    inner(
        lambda r: (
            httpx.Response(302, headers={"location": "https://pub.example/b"})
            if r.url.path == "/feed.ics"
            else httpx.Response(404)
        )
    )
    pol = policy.effective(True, may_use_private=False)
    with pytest.raises(Exception):  # noqa: B017 - the 404 ends it
        await fetch.fetch_feed(
            "https://pub.example/feed.ics", policy=pol, etag=None, last_modified=None,
            max_bytes=1000, transport_factory=factory,
        )  # fmt: skip
    assert len(hops) == 2 and all(h is pol for h in hops)


async def test_the_fetcher_receives_the_savers_policy(db_state):
    (sid,) = await seed(db_state, may_use_private=False)
    fetcher = Fetcher()
    await tick(db_state, fetcher, settings=ON)
    assert fetcher.calls[0]["policy"] == policy.effective(True, may_use_private=False)
    (flagged,) = await seed(db_state, slug="other", may_use_private=True)
    other = Fetcher()
    await tick(db_state, other, settings=ON)
    assert other.calls[0]["policy"] == policy.effective(True, may_use_private=True)
    assert sid and flagged


async def test_refresh_one_uses_the_same_policy(db_state):
    (sid,) = await seed(db_state, may_use_private=False)
    fetcher = Fetcher()
    from tests.feeds.subscriptions.refresh_support import NOW

    await refresh.refresh_one_async(
        db_state.session_factory, tenant_id="default", subscription_id=sid, now=NOW,
        settings=ON, fetcher=fetcher, utc_now=lambda: NOW,
    )  # fmt: skip
    assert fetcher.calls[0]["policy"] == policy.effective(True, may_use_private=False)


@pytest.mark.parametrize(
    ("previous", "changed", "saver", "expected"),
    [
        (False, True, True, True),  # a manager saves a new address: flagged
        (False, True, False, False),
        (True, True, False, False),  # a non-manager changes the address: cleared
        (True, True, True, True),
        (True, False, False, True),  # another edit leaves it
        (False, False, True, False),  # ...and never grants it
    ],
)
def test_the_flag_follows_the_address_not_other_edits(previous, changed, saver, expected):
    assert (
        policy.flag_after_save(previous, url_changed=changed, saver_may_use_private=saver)
        is expected
    )
