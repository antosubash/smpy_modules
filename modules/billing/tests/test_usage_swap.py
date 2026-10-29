"""``swap``: reserve and commit a new hold and release the old one, atomically.

The quota check counts the old hold's quantity as freed (the net delta), a
replayed key returns the same hold, an old hold of another tenant is refused,
and an old hold already settled makes it a plain reserve and commit. The
concurrent case (two swaps of one old hold) is in ``test_usage_hold_races``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_billing.contracts.metering import (
    Exceeded,
    Expired,
    Hold,
    HoldNotFound,
    IdempotencyConflict,
    Refused,
)
from sm_billing.models import Plan, UsageHold
from sqlalchemy import select, update
from usage_helpers import FAR, GAUGE, Clock, gauge_service, hold_statuses, in_use, seed_limits


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
    hold = await usage.swap(tenant, GAUGE, None, 5, "a", source="t", not_after=FAR)
    assert isinstance(hold, Hold) and hold.ok and not hold.replayed
    assert (hold.status, hold.expires_at, hold.quantity) == ("committed", None, 5)
    assert await in_use(factory, tenant) == 5
    refused = await usage.swap(tenant, GAUGE, None, 1, "b", source="t", not_after=FAR)
    assert isinstance(refused, Exceeded) and refused.requested == 1
    assert await hold_statuses(factory, tenant) == ["committed", "refused"]


async def test_the_old_quantity_counts_as_freed_at_the_limit(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 10})
    old = await usage.swap(tenant, GAUGE, None, 6, "a", source="t", not_after=FAR)
    await usage.reserve(tenant, GAUGE, 2, "other", source="t")  # level 8
    new = await usage.swap(
        tenant, GAUGE, old.id, 8, "b", source="t", not_after=FAR
    )  # net +2: exactly 10
    assert isinstance(new, Hold) and new.status == "committed"
    assert await in_use(factory, tenant) == 10
    assert await _statuses(factory, old.id, new.id) == ["released", "committed"]
    refused = await usage.swap(
        tenant, GAUGE, new.id, 9, "c", source="t", not_after=FAR
    )  # net +1: 11
    assert refused == Exceeded(used=10, limit=10, requested=1, period_end=None)
    # Refused: nothing written, the old hold still counts.
    assert await in_use(factory, tenant) == 10
    assert await _statuses(factory, new.id) == ["committed"]
    assert sorted(await hold_statuses(factory, tenant)) == [
        "committed",
        "held",
        "refused",
        "released",
    ]


async def test_a_shrink_is_admitted_even_over_the_limit(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 10})
    old = await usage.swap(tenant, GAUGE, None, 8, "a", source="t", not_after=FAR)
    async with factory() as s:  # the plan was lowered under the tenant
        await s.execute(update(Plan).where(Plan.key == f"p-{tenant[:8]}").values(limits={GAUGE: 3}))
        await s.commit()
    smaller = await usage.swap(tenant, GAUGE, old.id, 5, "b", source="t", not_after=FAR)
    assert isinstance(smaller, Hold) and await in_use(factory, tenant) == 5
    same = await usage.swap(tenant, GAUGE, smaller.id, 5, "c", source="t", not_after=FAR)
    assert isinstance(same, Hold) and await in_use(factory, tenant) == 5
    assert isinstance(
        await usage.swap(tenant, GAUGE, same.id, 6, "d", source="t", not_after=FAR), Exceeded
    )


async def test_a_replayed_key_returns_the_same_hold(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 10})
    old = await usage.swap(tenant, GAUGE, None, 4, "a", source="t", not_after=FAR)
    first = await usage.swap(tenant, GAUGE, old.id, 6, "b", source="t", not_after=FAR)
    again = await usage.swap(tenant, GAUGE, old.id, 6, "b", source="t", not_after=FAR)
    assert again.id == first.id and again.replayed and again.status == "committed"
    assert await in_use(factory, tenant) == 6  # counted once
    with pytest.raises(IdempotencyConflict):
        await usage.swap(tenant, GAUGE, old.id, 7, "b", source="t", not_after=FAR)
    await usage.release(first.id)
    late = await usage.swap(
        tenant, GAUGE, old.id, 6, "b", source="t", not_after=FAR
    )  # still the same hold
    assert (late.id, late.ok) == (first.id, False)
    assert await in_use(factory, tenant) == 0


async def test_a_settled_or_unknown_old_hold_is_a_plain_reserve(factory, usage, clock):
    tenant = await seed_limits(factory, {GAUGE: 6})
    gone = await usage.swap(tenant, GAUGE, None, 6, "a", source="t", not_after=FAR)
    await usage.release(gone.id)
    new = await usage.swap(
        tenant, GAUGE, gone.id, 6, "b", source="t", not_after=FAR
    )  # nothing freed
    assert isinstance(new, Hold) and await in_use(factory, tenant) == 6
    assert isinstance(
        await usage.swap(tenant, GAUGE, gone.id, 1, "c", source="t", not_after=FAR), Exceeded
    )
    unknown = "f" * 32
    assert isinstance(
        await usage.swap(tenant, GAUGE, unknown, 1, "d", source="t", not_after=FAR), Exceeded
    )


async def test_a_lapsed_held_old_hold_is_freed(factory, usage, clock):
    """Past its expiry but not yet swept, a ``held`` hold still counts in the
    gauge, so the swap frees it rather than double counting it."""
    tenant = await seed_limits(factory, {GAUGE: 6})
    lapsed = await usage.reserve(tenant, GAUGE, 6, "a", source="t", ttl=10)
    clock.now += timedelta(seconds=11)
    new = await usage.swap(tenant, GAUGE, lapsed.id, 6, "b", source="t", not_after=FAR)
    assert isinstance(new, Hold) and await in_use(factory, tenant) == 6
    assert (await _statuses(factory, lapsed.id))[0] not in ("held", "committed")


async def test_another_tenants_old_hold_is_refused(factory, usage):
    mine = await seed_limits(factory, {GAUGE: 10})
    theirs = await seed_limits(factory, {GAUGE: 10})
    their_hold = await usage.swap(theirs, GAUGE, None, 5, "a", source="t", not_after=FAR)
    with pytest.raises(HoldNotFound):
        await usage.swap(mine, GAUGE, their_hold.id, 5, "b", source="t", not_after=FAR)
    assert await in_use(factory, theirs) == 5 and await _statuses(factory, their_hold.id) == [
        "committed"
    ]
    assert await in_use(factory, mine) is None and await hold_statuses(factory, mine) == []
    with pytest.raises(HoldNotFound):  # an id longer than any issued names no hold
        await usage.swap(mine, GAUGE, "x" * 40, 5, "c", source="t", not_after=FAR)


async def test_a_refused_key_stays_refused(factory, usage):
    """The refusal is the key's outcome: a delayed duplicate of the call, or a
    retry once there is room, is refused again and changes nothing."""
    tenant = await seed_limits(factory, {GAUGE: 5})
    old = await usage.swap(tenant, GAUGE, None, 4, "a", source="t", not_after=FAR)
    assert isinstance(
        await usage.swap(tenant, GAUGE, old.id, 6, "k", source="t", not_after=FAR), Exceeded
    )
    async with factory() as s:  # room now
        await s.execute(
            update(Plan).where(Plan.key == f"p-{tenant[:8]}").values(limits={GAUGE: 50})
        )
        await s.commit()
    assert isinstance(
        await usage.swap(tenant, GAUGE, old.id, 6, "k", source="t", not_after=FAR), Exceeded
    )
    assert await in_use(factory, tenant) == 4
    assert await hold_statuses(factory, tenant) == ["committed", "refused"]
    assert await _statuses(factory, old.id) == ["committed"]
    fresh = await usage.swap(
        tenant, GAUGE, old.id, 6, "k2", source="t", not_after=FAR
    )  # a new key may
    assert isinstance(fresh, Hold) and await in_use(factory, tenant) == 6


async def test_a_replay_must_be_the_same_call(factory, usage):
    tenant = await seed_limits(factory, {GAUGE: 10})
    old = await usage.swap(tenant, GAUGE, None, 2, "a", source="t", not_after=FAR)
    new = await usage.swap(tenant, GAUGE, old.id, 3, "b", source="t", not_after=FAR)
    for other_old, source in ((None, "t"), ("e" * 32, "t"), (old.id, "u")):
        with pytest.raises(IdempotencyConflict):
            await usage.swap(tenant, GAUGE, other_old, 3, "b", source=source, not_after=FAR)
    assert (await usage.swap(tenant, GAUGE, old.id, 3, "b", source="t", not_after=FAR)).id == new.id
    assert isinstance(
        await usage.swap(tenant, GAUGE, new.id, 20, "c", source="t", not_after=FAR), Exceeded
    )
    with pytest.raises(IdempotencyConflict):  # a refused key answers only its own call
        await usage.swap(tenant, GAUGE, new.id, 19, "c", source="t", not_after=FAR)


async def test_a_refused_replay_answers_the_original_refusal(factory, usage):
    """The refusal's details are the key's, not the moment's: the same
    ``used``, ``limit`` and ``requested`` (the delta) however the gauge moved."""
    tenant = await seed_limits(factory, {GAUGE: 10})
    old = await usage.swap(tenant, GAUGE, None, 4, "a", source="t", not_after=FAR)
    other = await usage.reserve(tenant, GAUGE, 3, "other", source="t")  # level 7
    first = await usage.swap(tenant, GAUGE, old.id, 9, "k", source="t", not_after=FAR)
    assert first == Exceeded(used=7, limit=10, requested=5, period_end=None)
    await usage.release(other.id)
    async with factory() as s:
        await s.execute(
            update(Plan).where(Plan.key == f"p-{tenant[:8]}").values(limits={GAUGE: 50})
        )
        await s.commit()
    assert await usage.swap(tenant, GAUGE, old.id, 9, "k", source="t", not_after=FAR) == first


async def test_a_call_past_its_deadline_is_expired_and_changes_nothing(factory, usage, clock):
    """Billing enforces the caller's deadline: a swap arriving after
    ``not_after`` - however long its key's earlier outcome has been gone - is
    ``Expired``, recorded under the key, and never mutates."""
    tenant = await seed_limits(factory, {GAUGE: 50})
    old = await usage.swap(tenant, GAUGE, None, 4, "a", source="t", not_after=FAR)
    deadline = clock.now - timedelta(seconds=1)
    late = await usage.swap(tenant, GAUGE, old.id, 9, "k", source="t", not_after=deadline)
    assert late == Expired(idempotency_key="k", not_after=deadline)
    assert not late.ok and await in_use(factory, tenant) == 4
    assert await _statuses(factory, old.id) == ["committed"]
    again = await usage.swap(tenant, GAUGE, old.id, 9, "k", source="t", not_after=FAR)
    assert again == late  # the key's outcome, even with a later deadline
    assert await hold_statuses(factory, tenant) == ["committed", "expired_call"]


async def test_get_hold_by_key_reports_the_keys_outcome(factory, usage, clock):
    tenant = await seed_limits(factory, {GAUGE: 5})
    held = await usage.swap(tenant, GAUGE, None, 4, "a", source="t", not_after=FAR)
    await usage.swap(tenant, GAUGE, held.id, 9, "b", source="t", not_after=FAR)  # refused
    past = clock.now - timedelta(seconds=1)
    await usage.swap(tenant, GAUGE, held.id, 5, "c", source="t", not_after=past)
    found = await usage.get_hold_by_key(tenant, GAUGE, "a")
    assert isinstance(found, Hold) and (found.id, found.status) == (held.id, "committed")
    assert await usage.get_hold_by_key(tenant, GAUGE, "b") == Refused("b", "limit")
    assert await usage.get_hold_by_key(tenant, GAUGE, "c") == Refused("c", "deadline")
    assert await usage.get_hold_by_key(tenant, GAUGE, "nope") is None
    other = await seed_limits(factory, {GAUGE: 5})
    assert await usage.get_hold_by_key(other, GAUGE, "a") is None  # tenant-scoped
    assert await in_use(factory, tenant) == 4  # read-only
