"""The per-server spacing follows the address actually contacted: aliases of one server (any number
of names, a trailing dot, an IP in another spelling, an IPv6 /64, redirects, decoy addresses) share
one spacing, enforced on the pinned, validated IP before connecting, for the first request, every
redirect hop and each address a fetch tries."""

from __future__ import annotations

import logging
from datetime import timedelta
from itertools import pairwise

import httpx
import pytest
from sm_events.core import constants
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.importing.janitor import janitor_async
from sm_events.feeds.subscriptions import fetch, refresh, target_gate, urls
from sm_events.models import FetchTarget
from sqlalchemy import select

from tests.feeds.subscriptions.refresh_support import NOW, load, seed
from tests.support.net import PUBLIC_IP, ics, inner, resolver  # noqa: F401
from tests.support.subscriptions import seed_calendar

pytestmark = pytest.mark.unbound_tenant
SPACING = timedelta(seconds=constants.SUBSCRIPTION_TARGET_SPACING_SECONDS)


class World:
    """A clock the gate's waiting advances, and the times a connection was made."""

    def __init__(self, monkeypatch) -> None:
        self.now = NOW
        self.slept: list[float] = []
        self.connections: list[tuple[str, object]] = []  # (ip, when)

        async def sleep(seconds: float) -> None:
            self.slept.append(seconds)
            self.now += timedelta(seconds=seconds)

        monkeypatch.setattr(target_gate, "_sleep", sleep)

    def at(self, ip: str) -> list:
        return [when for host, when in self.connections if host == ip]


@pytest.fixture
def world(monkeypatch):
    return World(monkeypatch)


def _wired(world, inner, handler):  # noqa: F811
    def wrapped(request: httpx.Request) -> httpx.Response:
        world.connections.append((request.url.host, world.now))
        return handler(request)

    return inner(wrapped)


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


def test_ipv6_addresses_of_one_network_share_a_target_key():
    key = target_gate.target_key
    assert key("2001:db8:1:2:aaaa:bbbb:cccc:dddd") == key("2001:db8:1:2::1") == "2001:db8:1:2::/64"
    assert key("2001:db8:1:3::1") != key("2001:db8:1:2::1")
    assert key("93.184.216.34") == "93.184.216.34"
    assert key("::ffff:93.184.216.34") == "93.184.216.34"


async def _refresh_all(db_state, ids, world):
    results = []
    for sid in ids:
        results.append(
            await refresh.refresh_one_async(
                db_state.session_factory,
                tenant_id="default",
                subscription_id=sid,
                now=NOW,
                settings=EventsSettings(),
                fetcher=fetch.fetch_feed,
                utc_now=lambda: world.now,
            )
        )
    return results


async def _seed_hosts(db_state, hosts):
    ids = []
    for n, host in enumerate(hosts):
        (sid,) = await seed(
            db_state, slug=f"c{n}", url=f"https://{host}/feed.ics", next_fetch_at=NOW - SPACING
        )
        ids.append(sid)
    return ids


def _spaced(times) -> bool:
    return all(b - a >= SPACING for a, b in pairwise(times))


async def test_twenty_names_for_one_server_are_spaced(
    db_state,
    resolver,  # noqa: F811
    inner,  # noqa: F811
    world,
    caplog,
):
    hosts = [f"a{n}.wild.example" for n in range(20)]
    for host in hosts:
        resolver[host] = [PUBLIC_IP]
    _wired(world, inner, lambda r: ics())
    ids = await _seed_hosts(db_state, hosts)
    with caplog.at_level(logging.DEBUG):
        results = await _refresh_all(db_state, ids, world)
    assert results == ["stored"] * 20  # every feed is served, one after another
    times = world.at(PUBLIC_IP)
    assert len(times) == 20 and _spaced(times)  # never two connections within a spacing
    ours = [r for r in caplog.records if r.name.startswith(("sm_events", "httpx", "httpcore"))]
    for text in (r.getMessage() + repr(r.__dict__) for r in ours):
        assert PUBLIC_IP not in text and "wild.example" not in text  # no host or address logged
    for sid in ids:
        sub = await load(db_state, sid)
        assert (sub.error_code, sub.consecutive_failures, sub.slow_count) == (None, 0, 0)


async def test_twenty_hosts_redirecting_to_one_target_reach_it_spaced(
    db_state,
    resolver,  # noqa: F811
    inner,  # noqa: F811
    world,
):
    hosts = [f"r{n}.example" for n in range(20)]
    for n, host in enumerate(hosts):
        resolver[host] = [f"93.184.{n}.1"]
    resolver["target.example"] = [PUBLIC_IP]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "target.example":
            return ics()
        return httpx.Response(302, headers={"location": "https://target.example/real.ics"})

    _wired(world, inner, handler)
    ids = await _seed_hosts(db_state, hosts)
    results = await _refresh_all(db_state, ids, world)
    assert results == ["stored"] * 20
    assert len(world.at(PUBLIC_IP)) == 20 and _spaced(world.at(PUBLIC_IP))


async def test_a_redirect_inside_one_fetch_to_the_same_server_is_not_throttled(
    db_state,
    resolver,  # noqa: F811
    inner,  # noqa: F811
    world,
):
    resolver["one.example"] = [PUBLIC_IP]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://one.example/final.ics"})
        return ics()

    _wired(world, inner, handler)
    (sid,) = await seed(db_state, url="https://one.example/start", next_fetch_at=NOW - SPACING)
    assert (await _refresh_all(db_state, [sid], world)) == ["stored"]
    assert len(world.connections) == 2 and world.slept == []  # both hops, no waiting


async def test_decoy_addresses_do_not_buy_parallel_connections_to_the_real_server(
    db_state,
    resolver,  # noqa: F811
    inner,  # noqa: F811
    world,
):
    """Each name answers [its own unreachable decoy, the shared target]: the spacing is checked on
    every address a fetch connects to, so the target is still reached one spacing apart."""
    hosts = [f"d{n}.example" for n in range(20)]
    for n, host in enumerate(hosts):
        resolver[host] = [f"93.184.1.{n + 1}", PUBLIC_IP]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != PUBLIC_IP:
            raise httpx.ConnectError("refused")  # the decoy does not answer
        return ics()

    _wired(world, inner, handler)
    ids = await _seed_hosts(db_state, hosts)
    results = await _refresh_all(db_state, ids, world)
    assert results == ["stored"] * 20
    assert _spaced(world.at(PUBLIC_IP))
    for sid in ids:  # a decoy that refused is that address's attempt, not the feed's fault
        assert (await load(db_state, sid)).consecutive_failures == 0


async def test_a_server_busy_beyond_a_spacing_defers_the_feed_without_failing_it(
    db_state,
    resolver,  # noqa: F811
    inner,  # noqa: F811
    world,
):
    resolver["busy.example"] = [PUBLIC_IP]
    seen = _wired(world, inner, lambda r: ics())
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            db.add(FetchTarget(ip=PUBLIC_IP, last_attempt_at=NOW + 4 * SPACING))  # booked ahead
            await db.commit()
    ids = await _seed_hosts(db_state, ["busy.example"])
    assert (await _refresh_all(db_state, ids, world)) == ["deferred"]
    assert seen == [] and world.slept == []  # nothing contacted, no long wait
    sub = await load(db_state, ids[0])
    assert (sub.status, sub.error_code, sub.consecutive_failures, sub.slow_count) == (
        "pending", None, 0, 0,
    )  # fmt: skip
    assert sub.next_fetch_at >= NOW + SPACING


async def test_the_janitor_forgets_old_targets_and_stores_no_url(db_state):
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            await seed_calendar(db, "j")  # the janitor visits tenants that have data
            db.add(FetchTarget(ip="93.184.216.34", last_attempt_at=NOW - timedelta(hours=2)))
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


async def test_the_gate_admits_one_caller_per_spacing_even_concurrently(db_state, monkeypatch):
    import asyncio

    from sm_events.feeds.subscriptions.errors import FetchFailure
    from sm_events.feeds.subscriptions.target_gate import TargetGate

    async def instant(_seconds: float) -> None:  # an early caller does not really wait
        return None

    monkeypatch.setattr(target_gate, "_sleep", instant)

    async def one():
        try:
            await TargetGate(db_state.session_factory, "default", lambda: NOW)(PUBLIC_IP)
        except FetchFailure as late:
            assert late.code == "try_later"
            return False
        return True

    won = await asyncio.gather(*(one() for _ in range(10)))
    # at one instant exactly one is admitted at once; the others ask again one spacing later and
    # again exactly one of those wins: atomic (real concurrency on Postgres)
    assert won.count(True) == 2
