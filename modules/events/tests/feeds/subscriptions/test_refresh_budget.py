"""The tick's bounds, fairness across tenants, takeover of a dead lease, and refresh-one."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.subscriptions import launch, lease, refresh
from sm_events.models import Subscription
from sqlalchemy import update

from tests.feeds.subscriptions.refresh_support import (
    FEED,
    NOW,
    Fetcher,
    load,
    ok,
    seed,
    tick,
)

pytestmark = pytest.mark.unbound_tenant


async def _tenants(db_state, tenants, per_tenant=1):
    """``per_tenant`` due feeds in each of ``tenants`` tenants (each tenant's share of a tick is
    limited in SQL, so a budget test needs several)."""
    for n in range(tenants):
        for calendar in range(per_tenant):
            await seed(db_state, tenant=f"t{n}", count=1, slug=f"x{calendar}")


async def test_budget_fetch_count(db_state):
    await _tenants(db_state, 9, per_tenant=3)  # 27 chosen (3 each), 20 fit the tick
    fetcher = Fetcher()
    got = await tick(db_state, fetcher)
    assert (got["fetched"], got["skipped_budget"]) == (20, 7)
    assert len(fetcher.calls) == constants.SUBSCRIPTION_TICK_FETCHES


async def test_budget_bytes(db_state, monkeypatch):
    await _tenants(db_state, 6)
    monkeypatch.setattr(constants, "SUBSCRIPTION_TICK_BYTES", len(FEED) * 2)
    got = await tick(db_state, Fetcher())
    assert (got["fetched"], got["skipped_budget"]) == (2, 4)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


async def test_budget_seconds(db_state):
    await _tenants(db_state, 5)
    clock = Clock()

    class Slow(Fetcher):
        async def __call__(self, url, **kw):
            clock.t += 20  # each fetch takes 20 of the tick's 45 seconds
            return await super().__call__(url, **kw)

    got = await tick(db_state, Slow(), clock=clock)
    # 45 s budget, a fetch starts only with 30 s left: the first (45 left) runs, the next sees 25.
    assert (got["fetched"], got["skipped_budget"]) == (1, 4)


async def test_fair_across_tenants(db_state):
    for tenant, age in (("a", 5), ("b", 1)):  # a's feeds are far older, b still gets its share
        for slug in ("x", "y"):
            await seed(
                db_state,
                tenant=tenant,
                count=5,
                slug=slug,
                next_fetch_at=NOW - timedelta(hours=age),
            )
    fetcher = Fetcher()
    got = await tick(db_state, fetcher)
    hosts = [c["url"].split("//")[1][0] for c in fetcher.calls]
    share = constants.SUBSCRIPTION_TICK_FETCHES // 2  # equal shares of the tick's budget
    assert got["tenants"] == 2 and hosts.count("a") == hosts.count("b") == share


async def test_one_tenant_raising_does_not_stop_others(db_state, monkeypatch):
    (a,) = await seed(db_state, tenant="a", slug="x")
    (b,) = await seed(db_state, tenant="b", slug="x")
    real = lease.claim

    async def claim(db, sid, **kw):
        if sid == a:
            raise RuntimeError("database hiccup")
        return await real(db, sid, **kw)

    monkeypatch.setattr(refresh.lease, "claim", claim)
    got = await tick(db_state, Fetcher())
    assert (got["fetched"], got["failed"]) == (1, 1)
    assert (await load(db_state, b, "b")).status == "ok"


async def test_a_dead_workers_lease_is_taken_over_and_a_live_one_respected(db_state):
    live, dead = await seed(db_state, count=2)
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            await db.execute(
                update(Subscription)
                .where(Subscription.id == live)
                .values(lease_owner="alive", lease_until=NOW + timedelta(minutes=1))
            )
            await db.execute(
                update(Subscription)
                .where(Subscription.id == dead)
                .values(lease_owner="dead", lease_until=NOW - timedelta(minutes=1))
            )
            await db.commit()
    fetcher = Fetcher()
    got = await tick(db_state, fetcher)
    assert got["fetched"] == 1
    assert (await load(db_state, dead)).status == "ok" and (
        await load(db_state, dead)
    ).lease_owner is None
    assert (await load(db_state, live)).status == "pending"


async def test_a_lost_lease_cannot_store(db_state):
    (sid,) = await seed(db_state)

    class Thief(Fetcher):
        async def __call__(self, url, **kw):
            with tenant_scope("default"):  # another worker takes over while this one fetches
                async with db_state.session_factory() as db:
                    await db.execute(
                        update(Subscription)
                        .where(Subscription.id == sid)
                        .values(lease_owner="thief")
                    )
                    await db.commit()
            return await super().__call__(url, **kw)

    got = await tick(db_state, Thief())
    assert got["lease_lost"] == 1 and got["fetched"] == 0
    sub = await load(db_state, sid)
    assert (sub.generation, sub.item_count, sub.lease_owner) == (0, 0, "thief")


async def test_refresh_one_runs_the_same_guarded_fetch(db_state):
    (sid,) = await seed(db_state)
    fetcher = Fetcher()
    outcome = await refresh.refresh_one_async(
        db_state.session_factory,
        tenant_id="default",
        subscription_id=sid,
        now=NOW,
        settings=__import__("sm_events.core.settings", fromlist=["x"]).EventsSettings(),
        fetcher=fetcher,
        utc_now=lambda: NOW,
    )
    assert outcome == "stored" and len(fetcher.calls) == 1
    again = await refresh.refresh_one_async(
        db_state.session_factory,
        tenant_id="default",
        subscription_id=sid,
        now=NOW,
        settings=__import__("sm_events.core.settings", fromlist=["x"]).EventsSettings(),
        fetcher=fetcher,
        utc_now=lambda: NOW,
    )
    assert again == "busy" and len(fetcher.calls) == 1  # not due any more


async def test_refresh_one_skips_when_leased(db_state):
    (sid,) = await seed(db_state, lease_owner="other", lease_until=NOW + timedelta(minutes=1))
    from sm_events.core.settings import EventsSettings

    fetcher = Fetcher()
    outcome = await refresh.refresh_one_async(
        db_state.session_factory, tenant_id="default", subscription_id=sid, now=NOW,
        settings=EventsSettings(), fetcher=fetcher, utc_now=lambda: NOW,
    )  # fmt: skip
    assert outcome == "busy" and fetcher.calls == []


async def test_refresh_one_eager_runs_inline_after_commit(db_state, monkeypatch):
    from simple_module_db import finalize_session, mark_written
    from sm_events.core.settings import EventsSettings

    (sid,) = await seed(db_state)
    fetcher = Fetcher(ok())
    monkeypatch.setattr(launch, "celery_eager", lambda: True)
    monkeypatch.setattr(refresh, "fetch_feed", fetcher)
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            launch.refresh_one(
                db, tenant_id="default", subscription_id=sid,
                session_factory=db_state.session_factory, settings=EventsSettings(),
            )  # fmt: skip
            assert fetcher.calls == []  # nothing before the commit
            mark_written(db)  # the service has written (made it due) by now
            await finalize_session(db)
    assert len(fetcher.calls) == 1
    assert (await load(db_state, sid)).status == "ok"


async def test_refresh_one_enqueues_when_not_eager(db_state, monkeypatch):
    sent = []
    monkeypatch.setattr(launch, "celery_eager", lambda: False)
    monkeypatch.setattr(
        launch, "enqueue_after_commit", lambda db, task, *a, **k: sent.append((task, a, k))
    )
    (sid,) = await seed(db_state)
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            launch.refresh_one(db, tenant_id="default", subscription_id=sid)
    assert sent == [(constants.REFRESH_SUBSCRIPTION, ("default", str(sid)), {})]
