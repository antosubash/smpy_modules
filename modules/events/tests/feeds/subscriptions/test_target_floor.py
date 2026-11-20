"""The per-target fetch floor follows the address actually contacted: aliases of one server (any
number of names, a trailing dot, an IP in another spelling, redirects) share one floor, enforced
on the pinned, validated IP before connecting, for the first request and every redirect hop."""

from __future__ import annotations

import logging
from datetime import timedelta

import httpx
import pytest
from sm_events.core import constants
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.importing.janitor import janitor_async
from sm_events.feeds.subscriptions import fetch, refresh, urls
from sm_events.models import FetchTarget
from sqlalchemy import select

from tests.feeds.subscriptions.refresh_support import NOW, load, seed
from tests.support.net import PUBLIC_IP, ics, inner, resolver  # noqa: F401
from tests.support.subscriptions import seed_calendar

pytestmark = pytest.mark.unbound_tenant
FLOOR = timedelta(seconds=constants.SUBSCRIPTION_HOST_FLOOR_SECONDS)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("https://Cal.Example/a.ics", "https://cal.example./b.ics"),
        ("https://bücher.example/a.ics", "https://xn--bcher-kva.example/a.ics"),
        ("https://[::1]/a.ics", "https://[0:0:0:0:0:0:0:1]/a.ics"),
        ("https://[2001:DB8::1]/a.ics", "https://[2001:db8:0:0:0:0:0:1]/b.ics"),
    ],
)
def test_spellings_of_one_host_share_a_key(a, b):
    assert urls.host_of(a) == urls.host_of(b) != ""


async def _refresh_all(db_state, ids, now):
    results = []
    for sid in ids:
        results.append(
            await refresh.refresh_one_async(
                db_state.session_factory,
                tenant_id="default",
                subscription_id=sid,
                now=now,
                settings=EventsSettings(),
                fetcher=fetch.fetch_feed,
                utc_now=lambda: now,
            )
        )
    return results


async def _seed_hosts(db_state, hosts):
    ids = []
    for n, host in enumerate(hosts):
        (sid,) = await seed(
            db_state, slug=f"c{n}", url=f"https://{host}/feed.ics", next_fetch_at=NOW - FLOOR
        )
        ids.append(sid)
    return ids


async def test_twenty_names_for_one_server_get_one_connection_per_window(
    db_state,
    resolver,  # noqa: F811
    inner,  # noqa: F811
    caplog,
):
    hosts = [f"a{n}.wild.example" for n in range(20)]
    for host in hosts:
        resolver[host] = [PUBLIC_IP]
    seen = inner(lambda r: ics())
    ids = await _seed_hosts(db_state, hosts)
    with caplog.at_level(logging.DEBUG):
        results = await _refresh_all(db_state, ids, NOW)
    assert len(seen) == 1 and results.count("stored") == 1  # one connection to the one server
    ours = [r for r in caplog.records if r.name.startswith(("sm_events", "httpx", "httpcore"))]
    for text in (r.getMessage() + repr(r.__dict__) for r in ours):
        assert PUBLIC_IP not in text and "wild.example" not in text  # no host or address logged
    deferred = [await load(db_state, sid) for sid in ids if sid != _stored(results, ids)]
    for sub in deferred:  # rescheduled after the floor, and not failed
        assert (sub.status, sub.error_code, sub.consecutive_failures, sub.slow_count) == (
            "pending", None, 0, 0,
        )  # fmt: skip
        assert sub.next_fetch_at >= NOW + FLOOR - timedelta(seconds=1)
    later = NOW + FLOOR + timedelta(seconds=1)
    for sid in ids:  # the next window admits one more
        await _make_due(db_state, sid)
    await _refresh_all(db_state, ids, later)
    assert len(seen) == 2


def _stored(results, ids):
    return ids[results.index("stored")]


async def _make_due(db_state, sid):
    from sm_events.models import Subscription
    from sqlalchemy import update

    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            await db.execute(
                update(Subscription)
                .where(Subscription.id == sid)
                .values(next_fetch_at=NOW - FLOOR, last_attempt_at=None, lease_until=None)
            )
            await db.commit()


async def test_twenty_hosts_redirecting_to_one_target_connect_to_it_once(
    db_state,
    resolver,  # noqa: F811
    inner,  # noqa: F811
):
    hosts = [f"r{n}.example" for n in range(20)]
    for n, host in enumerate(hosts):
        resolver[host] = [f"93.184.{n}.1"]
    resolver["target.example"] = [PUBLIC_IP]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "target.example":
            return ics(**{"content-type": "text/calendar"})
        return httpx.Response(302, headers={"location": "https://target.example/real.ics"})

    seen = inner(handler)
    ids = await _seed_hosts(db_state, hosts)
    results = await _refresh_all(db_state, ids, NOW)
    to_target = [r for r in seen if r.headers["host"] == "target.example"]
    assert len(to_target) == 1  # twenty redirectors, one connection to the target
    assert results.count("stored") == 1
    for sid in ids:
        sub = await load(db_state, sid)
        assert sub.status in ("ok", "pending") and sub.error_code is None
        assert sub.consecutive_failures == 0


async def test_a_redirect_inside_one_fetch_to_the_same_server_is_not_throttled(
    db_state,
    resolver,  # noqa: F811
    inner,  # noqa: F811
):
    resolver["one.example"] = [PUBLIC_IP]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://one.example/final.ics"})
        return ics()

    seen = inner(handler)
    (sid,) = await seed(db_state, url="https://one.example/start", next_fetch_at=NOW - FLOOR)
    assert (await _refresh_all(db_state, [sid], NOW)) == ["stored"]
    assert len(seen) == 2  # both hops reached the one IP in the same fetch


async def test_the_janitor_forgets_old_targets_and_stores_no_url(db_state):
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            await seed_calendar(db, "j")  # the janitor visits tenants that have data
            db.add(FetchTarget(ip="93.184.216.34", last_attempt_at=NOW - timedelta(days=2)))
            db.add(FetchTarget(ip="93.184.216.35", last_attempt_at=NOW - timedelta(minutes=5)))
            await db.commit()
    await janitor_async(db_state.session_factory, now=NOW, relaunch=lambda *a: None)
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            left = (await db.execute(select(FetchTarget.ip))).scalars().all()
    assert left == ["93.184.216.35"]
    assert {c.name for c in FetchTarget.__table__.columns} == {
        "id", "tenant_id", "ip", "last_attempt_at",
    }  # fmt: skip


async def test_the_gate_admits_one_caller_per_floor_window_even_concurrently(db_state):
    import asyncio

    from sm_events.feeds.subscriptions.errors import FetchFailure
    from sm_events.feeds.subscriptions.target_gate import TargetGate

    async def one():
        try:
            await TargetGate(db_state.session_factory, "default", lambda: NOW)(PUBLIC_IP)
        except FetchFailure as late:
            assert late.code == "try_later" and late.retry_after == FLOOR.total_seconds()
            return False
        return True

    won = await asyncio.gather(*(one() for _ in range(10)))
    assert won.count(True) == 1  # atomic: exactly one connects (real concurrency on Postgres)
    # a whole floor later the next caller is admitted
    gate = TargetGate(db_state.session_factory, "default", lambda: NOW + FLOOR)
    await gate(PUBLIC_IP)
