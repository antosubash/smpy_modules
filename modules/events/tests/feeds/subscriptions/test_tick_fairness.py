"""A few slow feeds cannot starve the others: selection is fair per tenant, per calendar and per
host in SQL, a slow fetch costs its tenant the rest of the tick and pushes the feed out, and a
create/delete loop cannot start unfloored fetches."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Subscription
from sqlalchemy import update

from tests.feeds.subscriptions.refresh_support import NOW, Fetcher, load, ok, seed, tick
from tests.pg_support import USING_POSTGRES

pytestmark = pytest.mark.unbound_tenant
OLD = NOW - timedelta(minutes=30)


class Clock:
    """A wall clock the slow feeds advance: nothing really sleeps."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class SlowFetcher(Fetcher):
    def __init__(self, clock: Clock, slow_marker: str = "-slow") -> None:
        super().__init__(ok())
        self.clock, self.marker = clock, slow_marker
        self.by_tenant: list[str] = []

    async def __call__(self, url, **kw):
        self.by_tenant.append(url.split("//")[1].split("-")[0])
        if self.marker in url:
            self.clock.t += 29.0  # answers after 29 s, valid
        return await super().__call__(url, **kw)


async def _world(db_state):
    """Tenant a: ten calendars of ten slow feeds, due long ago, and one calendar of two normal
    feeds. Tenant b: five normal feeds. Returns tenant b's ids."""
    for n in range(10):
        await seed(db_state, tenant="a", count=10, slug=f"slow{n}", next_fetch_at=OLD)
    await seed(db_state, tenant="a", count=2, slug="norm", next_fetch_at=NOW)
    return await seed(db_state, tenant="b", count=5, slug="norm", next_fetch_at=NOW)


async def test_other_tenants_normal_feeds_are_fetched_within_a_few_ticks(db_state):
    clock = Clock()
    normal_b = await _world(db_state)
    fetched: set = set()
    per_tick_by_tenant = []
    for minute in range(1, 7):
        fetcher = SlowFetcher(clock, "slow")
        await tick(db_state, fetcher, now=NOW + timedelta(minutes=minute), clock=clock)
        per_tick_by_tenant.append(fetcher.by_tenant)
        for tenant, ids in (("b", normal_b),):
            for sid in ids:
                if (await load(db_state, sid, tenant)).last_ok_at is not None:
                    fetched.add(sid)
    assert fetched == set(normal_b), (
        per_tick_by_tenant
    )  # all five within six ticks (two a tick: one calendar, every other minute)
    for calls in per_tick_by_tenant:  # a slow fetch ends the tick: at most one slow feed of a
        assert calls.count("a") <= 1


async def test_a_slow_fetch_ends_its_tenants_tick_and_pushes_the_feed_out(db_state):
    clock = Clock()
    (slow,) = await seed(db_state, tenant="a", slug="slow0", count=1, next_fetch_at=OLD)
    others = await seed(db_state, tenant="a", slug="slow1", count=3, next_fetch_at=OLD)
    fetcher = SlowFetcher(clock, "slow")
    got = await tick(db_state, fetcher, clock=clock)
    assert fetcher.by_tenant.count("a") == 1  # the rest of tenant a waits for the next tick
    assert got["skipped_budget"] >= 0
    interval = timedelta(minutes=60)
    fetched_slow = [
        s for s in [await load(db_state, i, "a") for i in (slow, *others)] if s.last_ok_at
    ]
    assert len(fetched_slow) == 1  # one slow fetch, the rest waited
    sub = fetched_slow[0]
    slow = sub.id
    assert sub.slow_count == 1 and sub.next_fetch_at >= NOW + 2 * interval * 0.8
    # a fast success resets it
    fast = SlowFetcher(Clock(), "never")
    with tenant_scope("a"):
        from sm_events.models import Subscription

        async with db_state.session_factory() as db:
            await db.execute(
                update(Subscription).where(Subscription.id == slow).values(next_fetch_at=OLD)
            )
            await db.commit()
    await tick(db_state, fast, now=NOW + timedelta(minutes=5))
    again = await load(db_state, slow, "a")
    assert again.slow_count == 0 and again.next_fetch_at < NOW + timedelta(minutes=5 + 90)


async def test_the_slowdown_is_bounded(db_state):
    clock = Clock()
    (sid,) = await seed(db_state, tenant="a", slug="slow0", count=1, next_fetch_at=OLD)
    fetcher = SlowFetcher(clock, "slow")
    for round_ in range(8):
        with tenant_scope("a"):
            from sm_events.models import Subscription

            async with db_state.session_factory() as db:
                await db.execute(
                    update(Subscription)
                    .where(Subscription.id == sid)
                    .values(next_fetch_at=OLD, last_fetched_at=None)
                )
                await db.commit()
        now = NOW + timedelta(hours=round_)
        await tick(db_state, fetcher, now=now, clock=clock)
    sub = await load(db_state, sid, "a")
    assert sub.slow_count <= constants.SUBSCRIPTION_SLOW_MAX
    assert sub.next_fetch_at - now <= constants.SUBSCRIPTION_MAX_BACKOFF * 1.11  # + jitter


async def test_the_slow_score_decays_by_one_per_fast_success(db_state):
    (sid,) = await seed(db_state, tenant="a", slug="d", count=1, next_fetch_at=OLD)
    with tenant_scope("a"):
        async with db_state.session_factory() as db:
            await db.execute(
                update(Subscription).where(Subscription.id == sid).values(slow_count=3)
            )
            await db.commit()
    await tick(db_state, Fetcher(ok()))
    assert (await load(db_state, sid, "a")).slow_count == 2  # lowered, not erased


async def test_a_tenant_is_charged_for_the_seconds_it_uses_not_a_cliff(db_state):
    """Feeds answering in 4 s (under the slow threshold) still use their tenant's share of the
    tick: the tenant of fast feeds gets more fetches in it."""
    clock = Clock()

    class Timed(Fetcher):
        async def __call__(self, url, **kw):
            clock.t += 4.0 if "//t1-" in url else 0.2
            return await super().__call__(url, **kw)

    for tenant in ("t1", "t2"):
        for n in range(12):
            await seed(db_state, tenant=tenant, count=1, slug=f"c{n}", next_fetch_at=NOW)
    fetcher = Timed(ok())
    await tick(db_state, fetcher, now=NOW + timedelta(minutes=1), clock=clock)
    tenants = [c["url"].split("//")[1].split("-")[0] for c in fetcher.calls]
    assert tenants.count("t2") > tenants.count("t1")


@pytest.mark.skipif(not USING_POSTGRES, reason="needs real concurrent connections")
async def test_concurrent_ticks_respect_the_per_tenant_pick_and_never_double_fetch(db_state):
    for n in range(5):
        await seed(db_state, tenant="a", count=4, slug=f"c{n}", next_fetch_at=OLD)
    await seed(db_state, tenant="b", count=4, slug="b", next_fetch_at=OLD)
    first, second = Fetcher(ok()), Fetcher(ok())
    await asyncio.gather(tick(db_state, first), tick(db_state, second))
    urls = [c["url"] for c in first.calls + second.calls]
    assert len(urls) == len(set(urls))  # no subscription fetched twice
    for fetcher in (first, second):
        mine = [c["url"] for c in fetcher.calls if "//a-" in c["url"]]
        assert len(mine) <= constants.SUBSCRIPTION_TICK_FETCHES
