"""The under-count guard is atomic per tenant, and trusts only confirmed holds.

* Codex's trace (a): four concurrent uploads each pass the probe before any of
  them reserves, so all four land on room the under-counted image needs. The
  guard and the reserve now run under one lease per tenant
  (``images:quota:{tenant}``): exactly the room fits, the rest are refused.
* Codex's trace (b): a rehold's recorded replacement R that has expired used
  to count the image as covered. Only a replacement billing reports live does.
* No billing, or no limit: no lease is taken. A lease that cannot be had in
  time is ``QuotaBusy`` (503 ``quota_busy``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from simple_module_core import leases as core_leases
from sm_images import billing_guard, billing_ops
from sm_images.errors import QuotaBusy
from sm_images.ingest.slots import Slot, hold_slot
from sm_images.tenancy import DEFAULT_TENANT

from tests.billing_support import lapsed_image
from tests.pipeline_support import Blur, use_steps

T = DEFAULT_TENANT
LATER = timedelta(hours=2)
LEASE = f"images:quota:{T}"


@pytest.fixture
def blur():
    step = Blur()
    use_steps(step)
    return step


@pytest.fixture
def taken(monkeypatch) -> list[str]:
    """The names of the quota leases taken."""
    names: list[str] = []
    real = core_leases.lease

    def spy(name, *args, **kwargs):
        names.append(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(billing_guard, "lease", spy, raising=False)
    return names


def _settle(pipe, at: timedelta = LATER):
    return billing_ops.settle(pipe.db_state.session_factory, T, now=datetime.now(UTC) + at)


def _slot() -> Slot:
    return Slot(uuid.uuid4(), "k")


async def _uploads(factory, n: int, size: int) -> list[Slot]:
    return list(await asyncio.gather(*(hold_slot(factory, T, _slot(), size) for _ in range(n))))


async def test_concurrent_uploads_cannot_share_the_room_an_under_count_needs(
    pipe, blur, gauge, taken
):
    """Trace (a): with the image under-counted, room for one upload is left;
    four concurrent uploads must not all pass the probe."""
    factory = pipe.db_state.session_factory
    coll = await pipe.collection({"acme.blur": {}})
    _, _, h = await lapsed_image(pipe, gauge, coll)
    total = gauge.holds[h].quantity
    gauge.limit = gauge.level  # H's rehold is refused: the image is under-counted
    await _settle(pipe)
    size = total // 3
    assert size > 0
    gauge.limit = gauge.level + total + size  # room for the rehold and one upload
    gauge.reserve_delay = 0.05  # billing's latency: the probes interleave

    slots = await _uploads(factory, 4, size)

    assert sum(not s.refused for s in slots) == 1
    assert gauge.limit - gauge.level >= total  # the rehold's room is still there
    assert set(taken) == {LEASE}


async def test_a_healthy_quota_still_fits_concurrent_uploads(pipe, gauge, taken):
    factory = pipe.db_state.session_factory
    gauge.limit = 200
    gauge.reserve_delay = 0.02
    slots = await _uploads(factory, 4, 100)
    assert sum(not s.refused for s in slots) == 2
    assert gauge.level == 200
    assert not any(c[0] == "get_hold" for c in gauge.calls)  # nothing to confirm


async def test_an_expired_replacement_does_not_cover_the_image(pipe, blur, gauge, hooks):
    """Trace (b): the rehold recorded R, then R lapsed. The image is counted by
    nothing, so an upload of its size is refused until a rehold installs."""
    factory = pipe.db_state.session_factory
    coll = await pipe.collection({"acme.blur": {}})
    img, o, h = await lapsed_image(pipe, gauge, coll)
    total = gauge.holds[h].quantity
    gauge.limit = gauge.level + total  # exactly the rehold's room

    async def settler_dies(op):
        raise RuntimeError("the settler died after recording R")

    hooks["rehold.persisted"] = settler_dies
    await _settle(pipe)
    (r,) = [gauge.keys[k] for k in gauge.keys if "rehold-" in k]
    assert gauge.holds[r].status == "held"
    assert await billing_guard.under_counted_bytes(factory, T, gauge) == 0  # R counts it
    gauge.expire(r)
    assert await billing_guard.under_counted_bytes(factory, T, gauge) == total

    assert (await hold_slot(factory, T, _slot(), total)).refused
    assert (await hold_slot(factory, T, _slot(), 1)).refused

    for k in range(4):  # the rehold spends R and reserves anew: it takes the room
        await _settle(pipe, LATER * (k + 8))
    row = await pipe.row(img)
    assert row.storage_hold_id not in (o, h, r)
    assert gauge.holds[row.storage_hold_id].status == "committed"
    assert await billing_guard.under_counted_bytes(factory, T, gauge) == 0


async def test_no_billing_takes_no_lease(pipe, taken):
    slot = await hold_slot(pipe.db_state.session_factory, T, _slot(), 100)
    assert (slot.hold, slot.refused) == (None, False)
    assert taken == []


async def test_no_limit_takes_no_lease(pipe, gauge, taken):
    gauge.limit = None
    slot = await hold_slot(pipe.db_state.session_factory, T, _slot(), 100)
    assert slot.hold is not None
    assert taken == []


async def test_a_busy_quota_lease_is_quota_busy(pipe, gauge, monkeypatch):
    monkeypatch.setattr(billing_guard, "LEASE_WAIT", 0.1, raising=False)
    gauge.limit = 1000
    other = core_leases.lease(LEASE, ttl=30)
    assert await other.acquire()
    try:
        with pytest.raises(QuotaBusy) as exc:
            await hold_slot(pipe.db_state.session_factory, T, _slot(), 100)
        assert (exc.value.status_code, exc.value.code) == (503, "quota_busy")
        assert not [c for c in gauge.calls if c[0] == "reserve"]
    finally:
        await other.release()
    assert not (await hold_slot(pipe.db_state.session_factory, T, _slot(), 100)).refused
