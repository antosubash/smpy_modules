"""One tenant cannot hold every fetch slot: a per-tenant cap inside the install-wide one."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.subscriptions import lease, refresh

from tests.feeds.subscriptions.refresh_support import seed
from tests.pg_support import USING_POSTGRES

pytestmark = pytest.mark.unbound_tenant
NOW = utcnow()


async def _claim(db_state, tenant, sid, owner="w", now=NOW):
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            won = await lease.claim(db, sid, owner=owner, now=now)
            await db.commit()
            return won


async def _due(db_state, tenant, count, slug="x"):
    from datetime import timedelta as td

    return await seed(
        db_state, tenant=tenant, count=count, slug=slug, next_fetch_at=NOW - td(minutes=1)
    )


def test_the_caps_and_the_lease_are_related_on_purpose():
    per, total = (
        constants.SUBSCRIPTION_MAX_CONCURRENT_FETCHES_PER_TENANT,
        constants.SUBSCRIPTION_MAX_CONCURRENT_FETCHES,
    )
    assert 1 <= per <= max(1, total // 4)
    # a hung fetch ends at its total timeout and one store step later: the lease outlives that by
    # a margin and no more, so a hung fetch frees its slot soon after it is cut off
    seconds = constants.SUBSCRIPTION_LEASE.total_seconds()
    assert (
        constants.SUBSCRIPTION_FETCH_SECONDS + 15
        < seconds
        <= 5 * constants.SUBSCRIPTION_FETCH_SECONDS
    )


async def test_a_tenant_never_exceeds_its_cap_and_another_is_still_served(db_state, monkeypatch):
    monkeypatch.setattr(constants, "SUBSCRIPTION_MAX_CONCURRENT_FETCHES", 3)
    monkeypatch.setattr(constants, "SUBSCRIPTION_MAX_CONCURRENT_FETCHES_PER_TENANT", 2)
    hung = await _due(db_state, "a", 10)
    wins = [await _claim(db_state, "a", sid) for sid in hung]
    assert wins.count(True) == 2  # its own cap, although the install-wide one has room for 3
    (other,) = await _due(db_state, "b", 1)
    assert await _claim(db_state, "b", other) is True  # the third slot is b's
    (third,) = await _due(db_state, "c", 1)
    assert await _claim(db_state, "c", third) is False  # the install-wide cap is the outer bound


async def test_expired_leases_free_their_slots(db_state, monkeypatch):
    monkeypatch.setattr(constants, "SUBSCRIPTION_MAX_CONCURRENT_FETCHES_PER_TENANT", 1)
    first, second = await _due(db_state, "a", 2)
    assert await _claim(db_state, "a", first) is True
    assert await _claim(db_state, "a", second) is False
    later = NOW + constants.SUBSCRIPTION_LEASE + timedelta(seconds=1)
    assert await _claim(db_state, "a", second, now=later) is True


def test_the_tick_starts_at_a_different_tenant_each_minute():
    rows = [(t, n) for t in ("a", "b", "c") for n in range(2)]
    firsts = {
        refresh.rotate(rows, NOW.replace(second=0) + timedelta(minutes=m))[0][0] for m in range(3)
    }
    assert firsts == {"a", "b", "c"}
    assert sorted(refresh.rotate(rows, NOW)) == sorted(rows)


@pytest.mark.skipif(not USING_POSTGRES, reason="needs real concurrent connections")
async def test_concurrent_claims_respect_the_caps_exactly(db_state):
    ids = await _due(db_state, "a", 10)
    results = await asyncio.gather(
        *(_claim(db_state, "a", sid, owner=f"w{n}") for n, sid in enumerate(ids))
    )
    assert results.count(True) == constants.SUBSCRIPTION_MAX_CONCURRENT_FETCHES_PER_TENANT
