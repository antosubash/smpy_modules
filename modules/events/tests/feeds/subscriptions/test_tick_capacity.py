"""Throughput scales with the work that is due: one tenant alone can use the whole tick, and a
hundred feeds on three providers at the shortest interval are all refreshed within it."""

from __future__ import annotations

from datetime import timedelta
from itertools import pairwise

import pytest
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.subscriptions import refresh
from sm_events.feeds.subscriptions.attempt import attempt  # noqa: F401

from tests.feeds.subscriptions.refresh_support import NOW, Fetcher, load, ok, seed, tick
from tests.support.subscriptions import seed_calendar, seed_subscription

pytestmark = pytest.mark.unbound_tenant
SHORTEST = constants.SUBSCRIPTION_MIN_REFRESH_MINUTES


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class TimedFetcher(Fetcher):
    """Each fetch takes ``seconds`` of the fake clock and is logged with the tick it ran in."""

    def __init__(self, clock: Clock, seconds: float = 1.0) -> None:
        super().__init__(ok())
        self.clock, self.seconds = clock, seconds
        self.tick_no = 0
        self.log: list[tuple[str, int]] = []

    async def __call__(self, url, **kw):
        self.log.append((url, self.tick_no))
        self.clock.t += self.seconds
        return await super().__call__(url, **kw)


async def _hundred_on_three_hosts(db_state, owners: int = 5):
    ids = []
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            for c in range(10):
                cal = await seed_calendar(db, f"cal{c}")
                for n in range(10):
                    index = c * 10 + n
                    sub = await seed_subscription(
                        db, cal, label=f"s{index}", url=f"https://h{index % 3}.example/{index}.ics",
                        created_by=f"owner{index % owners}", refresh_minutes=SHORTEST,
                        next_fetch_at=NOW - timedelta(minutes=1),
                    )  # fmt: skip
                    ids.append(sub.id)
            await db.commit()
    return ids


async def test_a_hundred_feeds_on_three_providers_are_cycled_within_one_interval(db_state):
    ids = await _hundred_on_three_hosts(db_state)
    clock, fetcher = Clock(), None
    fetcher = TimedFetcher(clock)
    first_seen: dict[str, int] = {}
    for minute in range(1, SHORTEST + 1):
        fetcher.tick_no = minute
        await tick(db_state, fetcher, now=NOW + timedelta(minutes=minute), clock=clock)
        for url, at in fetcher.log:
            first_seen.setdefault(url, at)
        clock.t += 60.0
    assert len(first_seen) == 100, f"{100 - len(first_seen)} subscriptions never refreshed"
    # no feed is fetched more often than the per-subscription floor allows
    by_url: dict[str, list[int]] = {}
    for url, at in fetcher.log:
        by_url.setdefault(url, []).append(at)
    floor_minutes = constants.SUBSCRIPTION_REFRESH_NOW_SECONDS / 60
    for url, times in by_url.items():
        assert all(b - a >= floor_minutes for a, b in pairwise(times)), url
    assert (await load(db_state, ids[0])).last_ok_at is not None


async def test_one_tenant_alone_uses_the_whole_tick(db_state):
    for n in range(30):
        await seed(db_state, tenant="solo", count=1, slug=f"c{n}", next_fetch_at=NOW)
    fetcher = Fetcher(ok())
    got = await tick(db_state, fetcher, now=NOW + timedelta(minutes=1))
    assert got["fetched"] == constants.SUBSCRIPTION_TICK_FETCHES  # not a per-tenant sliver


async def test_unused_share_goes_to_the_tenants_that_have_work(db_state):
    await seed(db_state, tenant="small", count=2, slug="s", next_fetch_at=NOW)
    for n in range(30):
        await seed(db_state, tenant="big", count=1, slug=f"b{n}", next_fetch_at=NOW)
    fetcher = Fetcher(ok())
    await tick(db_state, fetcher, now=NOW + timedelta(minutes=1))
    tenants = [c["url"].split("//")[1].split("-")[0] for c in fetcher.calls]
    assert tenants.count("small") == 2  # its whole queue
    assert tenants.count("big") == constants.SUBSCRIPTION_TICK_FETCHES - 2  # the rest, no waste


async def test_members_share_a_tenants_tick_equally(db_state):
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            cal = await seed_calendar(db, "shared")
            for n in range(30):  # one member with many feeds, older than a colleague's
                await seed_subscription(
                    db, cal, label=f"a{n}", url=f"https://a{n}.example/x.ics", created_by="greedy",
                    next_fetch_at=NOW - timedelta(hours=2),
                )  # fmt: skip
            await seed_subscription(
                db, cal, label="mine", url="https://mine.example/x.ics", created_by="colleague",
                next_fetch_at=NOW - timedelta(minutes=5),
            )  # fmt: skip
            await db.commit()
    fetcher = Fetcher(ok())
    await tick(db_state, fetcher, now=NOW + timedelta(minutes=1))
    assert any("mine.example" in c["url"] for c in fetcher.calls)
    assert refresh  # imported for the module's own helpers
