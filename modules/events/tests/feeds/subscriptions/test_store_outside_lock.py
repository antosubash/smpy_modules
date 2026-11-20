"""The feed is parsed before the subscription row is locked, so an edit never waits for a parse,
and the fenced write still discards a result that went stale meanwhile."""

from __future__ import annotations

import asyncio
import threading

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.subscriptions import lease, store
from sm_events.models import ExternalItem, Subscription
from sqlalchemy import select, text, update

from tests.feeds.subscriptions.refresh_support import Fetcher, load, ok, seed, tick
from tests.pg_support import USING_POSTGRES

pytestmark = pytest.mark.unbound_tenant


async def test_the_parse_happens_before_the_row_is_locked(db_state, monkeypatch):
    (sid,) = await seed(db_state)
    order: list[str] = []
    real_prepare, real_fenced = store.prepare, lease.fenced

    def prepare(body, tz):
        order.append("parse")
        return real_prepare(body, tz)

    async def fenced(*a, **kw):
        order.append("lock")
        return await real_fenced(*a, **kw)

    monkeypatch.setattr(store, "prepare", prepare, raising=False)
    monkeypatch.setattr(lease, "fenced", fenced)
    await tick(db_state, Fetcher(ok()))
    # the claim reads the row under its lock, then the parse, and only then the store's lock
    assert order == ["lock", "parse", "lock"]
    assert (await load(db_state, sid)).item_count == 2


@pytest.mark.skipif(not USING_POSTGRES, reason="needs two real connections")
async def test_an_edit_during_a_slow_parse_is_not_blocked_and_the_stale_result_is_dropped(
    db_state, monkeypatch
):
    (sid,) = await seed(db_state)
    entered, release = threading.Event(), threading.Event()
    real = store.prepare

    def slow(body, tz):
        entered.set()
        assert release.wait(20)
        return real(body, tz)

    monkeypatch.setattr(store, "prepare", slow, raising=False)
    fetching = asyncio.create_task(tick(db_state, Fetcher(ok())))
    for _ in range(400):
        if entered.is_set():
            break
        await asyncio.sleep(0.05)
    assert entered.is_set()
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            await db.execute(text("SET LOCAL lock_timeout = '1s'"))  # a blocked edit would fail
            await db.execute(
                update(Subscription)
                .where(Subscription.id == sid)
                .values(label="edited", policy_generation=Subscription.policy_generation + 1)
            )
            await db.commit()
    release.set()
    got = await fetching
    assert got["fetched"] == 0 and got["lease_lost"] == 1  # the stale result was discarded
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            assert (await db.execute(select(ExternalItem))).scalars().all() == []
    assert (await load(db_state, sid)).label == "edited"
