"""``swap``: reserve and commit a new hold and release the old one, atomically.

The quota check counts the old hold's quantity as freed (the net delta), a
replayed key returns the same hold, an old hold of another tenant is refused,
and an old hold already settled makes it a plain reserve and commit. The
concurrent case (two swaps of one old hold) is in ``test_usage_hold_races``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_billing.contracts.metering import Exceeded, Hold, HoldNotFound, IdempotencyConflict
from sm_billing.models import Plan, UsageHold
from sqlalchemy import select, update
from usage_helpers import GAUGE, Clock, gauge_service, hold_statuses, in_use, seed_limits


@pytest.fixture
def factory(app):
    return app.state.sm.db.session_factory


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def usage(factory, clock):
    return gauge_service(factory, clock)


async def _statuses(factory, *ids: str) -> list[str]:
    async with factory() as s:
        found = dict((await s.execute(select(UsageHold.id, UsageHold.status))).all())
    return [found.get(i) for i in ids]


async def test_without_an_old_hold_it_reserves_and_commits(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 5})
    hold = await usage.swap(tenant, GAUGE, None, 5, "a", source="t")
    assert isinstance(hold, Hold) and hold.ok and not hold.replayed
    assert (hold.status, hold.expires_at, hold.quantity) == ("committed", None, 5)
    assert await in_use(factory, tenant) == 5
    refused = await usage.swap(tenant, GAUGE, None, 1, "b", source="t")
    assert isinstance(refused, Exceeded) and refused.requested == 1
    assert await hold_statuses(factory, tenant) == ["committed"]


async def test_the_old_quantity_counts_as_freed_at_the_limit(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 10})
    old = await usage.swap(tenant, GAUGE, None, 6, "a", source="t")
    await usage.reserve(tenant, GAUGE, 2, "other", source="t")  # level 8
    new = await usage.swap(tenant, GAUGE, old.id, 8, "b", source="t")  # net +2: exactly 10
    assert isinstance(new, Hold) and new.status == "committed"
    assert await in_use(factory, tenant) == 10
    assert await _statuses(factory, old.id, new.id) == ["released", "committed"]
    refused = await usage.swap(tenant, GAUGE, new.id, 9, "c", source="t")  # net +1: 11
    assert refused == Exceeded(used=10, limit=10, requested=1, period_end=None)
    # Refused: nothing written, the old hold still counts.
    assert await in_use(factory, tenant) == 10
    assert await _statuses(factory, new.id) == ["committed"]
    assert sorted(await hold_statuses(factory, tenant)) == ["committed", "held", "released"]


async def test_a_shrink_is_admitted_even_over_the_limit(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 10})
    old = await usage.swap(tenant, GAUGE, None, 8, "a", source="t")
    async with factory() as s:  # the plan was lowered under the tenant
        await s.execute(update(Plan).where(Plan.key == f"p-{tenant[:8]}").values(limits={GAUGE: 3}))
        await s.commit()
    smaller = await usage.swap(tenant, GAUGE, old.id, 5, "b", source="t")
    assert isinstance(smaller, Hold) and await in_use(factory, tenant) == 5
    same = await usage.swap(tenant, GAUGE, smaller.id, 5, "c", source="t")
    assert isinstance(same, Hold) and await in_use(factory, tenant) == 5
    assert isinstance(await usage.swap(tenant, GAUGE, same.id, 6, "d", source="t"), Exceeded)


async def test_a_replayed_key_returns_the_same_hold(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 10})
    old = await usage.swap(tenant, GAUGE, None, 4, "a", source="t")
    first = await usage.swap(tenant, GAUGE, old.id, 6, "b", source="t")
    again = await usage.swap(tenant, GAUGE, old.id, 6, "b", source="t")
    assert again.id == first.id and again.replayed and again.status == "committed"
    assert await in_use(factory, tenant) == 6  # counted once
    with pytest.raises(IdempotencyConflict):
        await usage.swap(tenant, GAUGE, old.id, 7, "b", source="t")
    await usage.release(first.id)
    late = await usage.swap(tenant, GAUGE, None, 6, "b", source="t")  # still the same hold
    assert (late.id, late.ok) == (first.id, False)
    assert await in_use(factory, tenant) == 0


async def test_a_settled_or_unknown_old_hold_is_a_plain_reserve(factory, usage, clock):
    tenant = await seed_limits(factory, {GAUGE: 6})
    gone = await usage.swap(tenant, GAUGE, None, 6, "a", source="t")
    await usage.release(gone.id)
    new = await usage.swap(tenant, GAUGE, gone.id, 6, "b", source="t")  # nothing freed
    assert isinstance(new, Hold) and await in_use(factory, tenant) == 6
    assert isinstance(await usage.swap(tenant, GAUGE, gone.id, 1, "c", source="t"), Exceeded)
    unknown = "f" * 32
    assert isinstance(await usage.swap(tenant, GAUGE, unknown, 1, "d", source="t"), Exceeded)


async def test_a_lapsed_held_old_hold_is_freed(factory, usage, clock):
    """Past its expiry but not yet swept, a ``held`` hold still counts in the
    gauge, so the swap frees it rather than double counting it."""
    tenant = await seed_limits(factory, {GAUGE: 6})
    lapsed = await usage.reserve(tenant, GAUGE, 6, "a", source="t", ttl=10)
    clock.now += timedelta(seconds=11)
    new = await usage.swap(tenant, GAUGE, lapsed.id, 6, "b", source="t")
    assert isinstance(new, Hold) and await in_use(factory, tenant) == 6
    assert (await _statuses(factory, lapsed.id))[0] not in ("held", "committed")


async def test_another_tenants_old_hold_is_refused(factory, usage):
    mine = await seed_limits(factory, {GAUGE: 10})
    theirs = await seed_limits(factory, {GAUGE: 10})
    their_hold = await usage.swap(theirs, GAUGE, None, 5, "a", source="t")
    with pytest.raises(HoldNotFound):
        await usage.swap(mine, GAUGE, their_hold.id, 5, "b", source="t")
    assert await in_use(factory, theirs) == 5 and await _statuses(factory, their_hold.id) == [
        "committed"
    ]
    assert await in_use(factory, mine) is None and await hold_statuses(factory, mine) == []
    with pytest.raises(HoldNotFound):  # an id longer than any issued names no hold
        await usage.swap(mine, GAUGE, "x" * 40, 5, "c", source="t")
