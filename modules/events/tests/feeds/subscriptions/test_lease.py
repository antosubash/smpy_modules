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
async def test_two_workers_one_fetch(db_state, db):
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
