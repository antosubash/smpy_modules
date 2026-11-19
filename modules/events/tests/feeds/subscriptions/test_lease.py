"""The beat's claim: compare-and-set, fenced stores, and a lease that expires."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.feeds.subscriptions import lease
from sm_events.models import Subscription
from sqlalchemy import select

from tests.pg_support import USING_POSTGRES
from tests.support.subscriptions import seed_calendar, seed_subscription

NOW = utcnow()


@pytest.fixture
async def sub(db):
    return await seed_subscription(db, await seed_calendar(db), next_fetch_at=NOW)


async def test_claim_once(db, sub):
    assert await lease.claim(db, sub.id, owner="a", now=NOW) is True
    assert await lease.claim(db, sub.id, owner="b", now=NOW) is False


async def test_a_claim_is_held_for_the_lease_and_then_reclaimable(db, sub):
    assert await lease.claim(db, sub.id, owner="a", now=NOW)
    late = NOW + constants.SUBSCRIPTION_LEASE + timedelta(seconds=1)
    assert await lease.claim(db, sub.id, owner="b", now=NOW + timedelta(seconds=30)) is False
    assert await lease.claim(db, sub.id, owner="b", now=late) is True
    row = (await db.execute(select(Subscription.lease_owner))).scalar_one()
    assert row == "b"


@pytest.mark.parametrize(
    "fields",
    [{"status": "paused"}, {"status": "disabled"}, {"is_deleted": True}, {"next_fetch_at": None}],
)
async def test_paused_disabled_deleted_not_due(db, fields):
    sub = await seed_subscription(db, await seed_calendar(db), **{"next_fetch_at": NOW, **fields})
    assert await lease.claim(db, sub.id, owner="a", now=NOW) is False


async def test_not_due_yet(db):
    sub = await seed_subscription(
        db, await seed_calendar(db), next_fetch_at=NOW + timedelta(minutes=5)
    )
    assert await lease.claim(db, sub.id, owner="a", now=NOW) is False


@pytest.mark.parametrize("status", ["pending", "ok", "error"])
async def test_every_live_status_is_due(db, status):
    sub = await seed_subscription(db, await seed_calendar(db), status=status, next_fetch_at=NOW)
    assert await lease.claim(db, sub.id, owner="a", now=NOW) is True


async def test_lost_lease_cannot_store(db, sub):
    sid = sub.id
    assert await lease.claim(db, sid, owner="a", now=NOW)
    assert (await lease.fenced(db, sid, owner="a", now=NOW)) is not None
    later = NOW + constants.SUBSCRIPTION_LEASE + timedelta(seconds=5)
    assert await lease.claim(db, sid, owner="b", now=later)
    assert await lease.fenced(db, sid, owner="a", now=later) is None
    assert (await lease.fenced(db, sid, owner="b", now=later)) is not None


async def test_an_expired_lease_cannot_store_even_unclaimed(db, sub):
    await lease.claim(db, sub.id, owner="a", now=NOW)
    later = NOW + constants.SUBSCRIPTION_LEASE + timedelta(seconds=5)
    assert await lease.fenced(db, sub.id, owner="a", now=later) is None


async def test_release_clears_the_lease(db, sub):
    await lease.claim(db, sub.id, owner="a", now=NOW)
    held = await lease.fenced(db, sub.id, owner="a", now=NOW)
    await lease.release(db, held)
    await db.flush()
    row = (await db.execute(select(Subscription.lease_owner, Subscription.lease_until))).one()
    assert tuple(row) == (None, None)


@pytest.mark.skipif(not USING_POSTGRES, reason="needs two real connections")
async def test_two_workers_one_fetch(db_state, db, monkeypatch):
    monkeypatch.setattr(constants, "SUBSCRIPTION_MAX_CONCURRENT_FETCHES", 1000)
    cal = await seed_calendar(db)
    ids = [
        (await seed_subscription(db, cal, label=f"s{n}", next_fetch_at=NOW)).id for n in range(20)
    ]
    await db.commit()

    async def worker(name: str) -> set:
        won = set()
        async with db_state.session_factory() as session:
            for sid in ids:
                if await lease.claim(session, sid, owner=name, now=NOW):
                    won.add(sid)
            await session.commit()
        return won

    first, second = await asyncio.gather(worker("a"), worker("b"))
    assert first | second == set(ids)
    assert first & second == set()


async def test_an_install_wide_cap_on_simultaneous_fetches(db, monkeypatch):
    """Excess work waits: with the cap reached, a due subscription is not claimed."""
    monkeypatch.setattr(constants, "SUBSCRIPTION_MAX_CONCURRENT_FETCHES", 2)
    cal = await seed_calendar(db)
    subs = [await seed_subscription(db, cal, label=f"s{n}", next_fetch_at=NOW) for n in range(4)]
    assert await lease.claim(db, subs[0].id, owner="a", now=NOW)
    assert await lease.claim(db, subs[1].id, owner="a", now=NOW)
    assert await lease.claim(db, subs[2].id, owner="a", now=NOW) is False  # cap reached
    later = NOW + constants.SUBSCRIPTION_LEASE + timedelta(seconds=1)
    assert await lease.claim(db, subs[2].id, owner="a", now=later)  # the others' leases ended


async def test_a_plain_session_without_the_framework_listeners_holds_the_lease(db_state, db):
    """PR 8's lesson: the claim must hold on a bare ``AsyncSession`` (no listeners, no
    ``RequestSession``): the UPDATE itself is the lock, and it commits."""
    from sqlalchemy.ext.asyncio import AsyncSession

    sub = await seed_subscription(db, await seed_calendar(db), next_fetch_at=NOW)
    sid = sub.id
    await db.commit()
    async with AsyncSession(db_state.engine, expire_on_commit=False) as plain:
        assert await lease.claim(plain, sid, owner="plain", now=NOW)
        await plain.commit()
    async with AsyncSession(db_state.engine, expire_on_commit=False) as other:
        assert await lease.claim(other, sid, owner="other", now=NOW) is False
    row = (await db.execute(select(Subscription.lease_owner))).scalar_one()
    assert row == "plain"


@pytest.mark.skipif(not USING_POSTGRES, reason="needs real concurrent connections")
async def test_one_subscription_is_claimed_once_by_many_concurrent_sessions(db_state, db):
    sub = await seed_subscription(db, await seed_calendar(db), next_fetch_at=NOW)
    sid = sub.id
    await db.commit()

    async def claim(n: int) -> bool:
        async with db_state.session_factory() as session:
            won = await lease.claim(session, sid, owner=f"w{n}", now=NOW)
            await session.commit()
            return won

    results = await asyncio.gather(*(claim(n) for n in range(12)))
    assert results.count(True) == 1
