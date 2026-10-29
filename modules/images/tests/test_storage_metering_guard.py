"""Room freed for a quota-refused rehold goes to the rehold first.

Round 5 lets an image's old hold O be released once the rehold of its lapsed
current hold H is refused for quota, so the two never wait on each other. The
image is under-counted until the rehold fits. Without a guard, a new upload of
O's size takes exactly that room, the rehold is refused for good, and the
tenant stores the image for free. Every quota pre-check therefore counts the
gauge plus the bytes of under-counted images (``billing_guard``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sm_images import billing, billing_guard, billing_ops
from sm_images.errors import StorageQuotaExceeded
from sm_images.ingest.slots import Slot, hold_slot
from sm_images.tenancy import DEFAULT_TENANT

from tests.billing_support import held_image, lapsed_image
from tests.pipeline_support import Blur, use_steps

T = DEFAULT_TENANT
LATER = timedelta(hours=2)
WAIT = timedelta(seconds=45)  # past the release's wait, before the rehold's backoff


@pytest.fixture
def blur():
    step = Blur()
    use_steps(step)
    return step


def _settle(pipe, at: timedelta):
    return billing_ops.settle(pipe.db_state.session_factory, T, now=datetime.now(UTC) + at)


async def _fill(gauge, room: int) -> str:
    d = await gauge.reserve(T, billing.METER, 1, "D", source="t")
    await gauge.commit(d.id)
    gauge.limit = gauge.level + room
    return d.id


def _slot() -> Slot:
    return Slot(uuid.uuid4(), "k")


async def _web_check(pipe, gauge, qty: int) -> None:
    app = SimpleNamespace(state=SimpleNamespace(billing_usage=gauge))
    async with pipe.db_state.session_factory() as db:
        await billing.check(app, T, qty, db)


async def test_room_freed_for_a_refused_rehold_is_not_given_to_an_upload(pipe, blur, gauge):
    """Codex's quota-refused trace: O is released, its size is free, and an
    upload of that size is refused until the rehold has taken it."""
    factory = pipe.db_state.session_factory
    coll = await pipe.collection({"acme.blur": {}})
    img, o, h = await lapsed_image(pipe, gauge, coll)
    total = gauge.holds[h].quantity
    freed = gauge.holds[o].quantity
    d = await _fill(gauge, room=total - 1)  # the rehold fits only once O is released
    await _settle(pipe, LATER)  # H's rehold is refused for quota
    await _settle(pipe, LATER + WAIT)  # O gives way; the rehold is still backing off
    assert gauge.holds[o].status == "released"
    assert (await pipe.row(img)).storage_hold_id == h  # still under-counted
    assert await billing_guard.under_counted_bytes(factory, T) == total

    assert (await hold_slot(factory, T, _slot(), freed)).refused
    with pytest.raises(StorageQuotaExceeded):
        await _web_check(pipe, gauge, freed)
    assert sorted(x.id for x in gauge.live()) == [d]  # no probe left behind

    for k in range(4):  # the rehold's backoff passes: it takes the freed room
        await _settle(pipe, LATER * (k + 8))
    row = await pipe.row(img)
    assert row.storage_hold_id not in (o, h)
    assert gauge.holds[row.storage_hold_id].status == "committed"
    assert await billing_guard.under_counted_bytes(factory, T) == 0
    assert sorted(x.id for x in gauge.live()) == sorted([row.storage_hold_id, d])
    assert gauge.limit - gauge.level == freed - 1  # what is left is new room again
    assert not (await hold_slot(factory, T, _slot(), freed - 1)).refused


async def test_a_healthy_quota_takes_no_extra_billing_call(pipe, blur, gauge):
    factory = pipe.db_state.session_factory
    coll = await pipe.collection({"acme.blur": {}})
    await held_image(pipe, gauge, coll)
    gauge.limit = gauge.level + 10
    gauge.calls.clear()
    assert await billing_guard.under_counted_bytes(factory, T) == 0
    await _web_check(pipe, gauge, 10)
    assert not (await hold_slot(factory, T, _slot(), 10)).refused
    assert [c[0] for c in gauge.calls] == ["check", "reserve"]
    assert (await hold_slot(factory, T, _slot(), 1)).refused  # the gauge itself still binds


async def test_an_image_does_not_count_against_its_own_publication(pipe, blur, gauge):
    """A publication replaces the image's hold: its own lapsed bytes are not
    added on top of the total it reserves."""
    factory = pipe.db_state.session_factory
    coll = await pipe.collection({"acme.blur": {}})
    img, _, h = await lapsed_image(pipe, gauge, coll)
    gauge.limit = gauge.level  # the rehold is refused and stays pending
    await _settle(pipe, LATER)
    assert (await pipe.row(img)).storage_hold_id == h
    total = gauge.holds[h].quantity
    assert await billing_guard.under_counted_bytes(factory, T) == total
    assert await billing_guard.under_counted_bytes(factory, T, exclude=img) == 0
