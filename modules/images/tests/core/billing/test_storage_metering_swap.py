"""Every replacement of an image's hold is billing's atomic swap.

The traces that refuted the old two-call design, and the crash points around
the swap op. Each ends on :func:`assert_counted_once`: no op pending, every
image counted by exactly the one committed hold it names, of its
``storage_bytes``, and nothing else held.

* Round 5's deadlock: a replacement needed room the image's own old hold held.
* Codex's (v) expiry trace: an image counted by a hold that could lapse.
* The lease-stall trace: a holder that stalls past its exclusivity.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import finalize_session
from sm_images.core import billing
from sm_images.core.billing import ops as billing_ops
from sm_images.core.billing.settle import CLAIM
from sm_images.core.tenancy import DEFAULT_TENANT as T
from sm_images.ingest.slots import INGEST_CLAIM, Slot, hold_slot
from sm_images.jobs.janitor import purge_expired
from sm_images.models import Image
from sm_images.pipeline import storage_hold
from sm_images.pipeline.orchestrate import rerun_image

from tests.support.billing import assert_counted_once, held_image, ops
from tests.support.pipeline import Blur, jpeg, use_steps

LATER = CLAIM + timedelta(seconds=1)


class Crash(BaseException):
    """A worker dying mid-call: nothing after it runs, no ``except Exception``."""


class Sized(Blur):
    """A display mutator whose copy's size the test picks."""

    def __init__(self, dims: tuple[int, int]) -> None:
        super().__init__()
        self.dims = dims

    async def run(self, ctx):
        from sm_images.pipeline.step import StepOutcome

        await ctx.read_original()
        await ctx.write_display(jpeg(self.dims, "green"), "image/jpeg")
        return StepOutcome.completed({})


@pytest.fixture
def blur():
    step = Blur()
    use_steps(step)
    return step


def _settle(pipe, at: timedelta = LATER):
    return billing_ops.settle(pipe.db_state.session_factory, T, now=datetime.now(UTC) + at)


def _swaps(gauge) -> list[tuple[str, ...]]:
    return [c for c in gauge.calls if c[0] == "swap"]


def _crash_around_swap(monkeypatch, *, after: bool, then=None):
    """The executor's billing swap, once: crash before it reaches billing, or
    after billing swapped (``then`` runs there instead of crashing)."""
    real, state = billing.swap, {"armed": True}

    async def swap(*args, **kwargs):
        if not state.pop("armed", False):
            return await real(*args, **kwargs)
        if not after:
            raise Crash()
        hold = await real(*args, **kwargs)
        if then is None:
            raise Crash()
        await then()
        return hold

    monkeypatch.setattr(storage_hold.billing, "swap", swap)


async def test_a_grown_display_is_one_swap_from_the_old_hold(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed = await held_image(pipe, gauge, coll)
    await pipe.run(img)
    row = await pipe.row(img)
    assert row.display_key and row.storage_bytes > row.size_bytes
    (call,) = _swaps(gauge)[1:]
    assert call[1:3] == (seed, str(row.storage_bytes))
    assert gauge.holds[seed].status == "released"
    assert not [c for c in gauge.calls if c[0] in ("reserve", "commit", "release")]
    await assert_counted_once(pipe.db_state, gauge)


async def test_round5_trace_the_old_hold_frees_the_room_its_replacement_needs(pipe, blur, gauge):
    """Round 5: the replacement needed room the image's own old hold held, so
    the two waited on each other. A swap frees the old hold in the same step:
    at a full gauge it fits exactly when the net delta does."""
    coll = await pipe.collection({"acme.blur": {}})
    img, seed = await held_image(pipe, gauge, coll)
    other = await gauge.swap(T, billing.METER, None, 50, "another-image", source="t")
    grown = (await pipe.row(img)).size_bytes + len(jpeg((32, 24), "green"))
    gauge.limit = grown + 50  # room for the new total only once the old is freed
    await pipe.run(img)
    row = await pipe.row(img)
    assert (row.storage_bytes, row.display_generation) == (grown, 1)
    assert {h.id for h in gauge.live()} == {row.storage_hold_id, other.id}
    assert gauge.level == gauge.limit and gauge.holds[seed].status == "released"
    assert all(o.done_at for o in await ops(pipe.db_state))


async def test_a_shrink_is_swapped_after_the_commit_even_at_a_full_gauge(pipe, gauge):
    step = Sized((96, 72))
    use_steps(step)
    coll = await pipe.collection({"acme.blur": {}})
    img, _ = await held_image(pipe, gauge, coll)
    await pipe.run(img)
    big = (await pipe.row(img)).storage_bytes
    gauge.limit = gauge.level  # full
    step.dims = (8, 6)
    await rerun_image(pipe.runtime, T, img, "force")
    row = await pipe.row(img)
    assert (row.display_generation, row.storage_bytes < big) == (2, True)
    assert [o.op for o in await ops(pipe.db_state)] == ["swap", "swap"]  # grow, then shrink
    await assert_counted_once(pipe.db_state, gauge)


async def test_a_crash_before_the_billing_call_is_taken_over(pipe, blur, gauge, monkeypatch):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed = await held_image(pipe, gauge, coll)
    _crash_around_swap(monkeypatch, after=False)
    with pytest.raises(Crash):
        await pipe.run(img)
    (op,) = await ops(pipe.db_state)
    assert (op.op, op.done_at is None, op.claim_token is not None) == ("swap", True, True)
    assert await _settle(pipe, timedelta(0)) == 0  # still the executor's
    assert await _settle(pipe) >= 1  # its claim expired: a settler swaps and installs
    row = await pipe.row(img)
    assert (row.display_key, row.storage_bytes) == (None, row.size_bytes)  # nothing published
    assert row.storage_hold_id != seed
    await assert_counted_once(pipe.db_state, gauge)


async def test_a_crash_after_billing_swapped_before_the_image_update(
    pipe, blur, gauge, monkeypatch
):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed = await held_image(pipe, gauge, coll)
    _crash_around_swap(monkeypatch, after=True)
    with pytest.raises(Crash):
        await pipe.run(img)
    (swapped,) = gauge.live()  # counted once, by the swapped hold, while the op is pending
    assert gauge.holds[seed].status == "released"
    assert (await pipe.row(img)).storage_hold_id == seed
    await _settle(pipe)
    key = _swaps(gauge)[1][3]
    assert [c[3] for c in _swaps(gauge)].count(key) == 2  # the retry replayed the key
    row = await pipe.row(img)
    assert gauge.holds[swapped.id].status == "released"  # shrunk back: nothing was published
    assert (row.display_key, row.storage_bytes) == (None, row.size_bytes)
    await assert_counted_once(pipe.db_state, gauge)


async def test_lease_stall_trace_a_stalled_executor_cannot_install_over_a_takeover(
    pipe, blur, gauge, monkeypatch
):
    """The lease-stall trace: a holder stalls past its exclusivity and acts on
    stale state. Here the executor stalls after billing swapped; a settler takes
    the op over and installs; the executor's completion then finds the image
    moved on and our claim gone - it rolls back, and the run is planned again."""
    coll = await pipe.collection({"acme.blur": {}})
    img, _ = await held_image(pipe, gauge, coll)
    took = []

    async def takeover():
        took.append(await _settle(pipe))

    _crash_around_swap(monkeypatch, after=True, then=takeover)
    await pipe.run(img)
    assert took and took[0] >= 1
    row = await pipe.row(img)
    assert row.display_generation == 1  # the replanned run published
    assert row.storage_bytes > row.size_bytes
    await assert_counted_once(pipe.db_state, gauge)


async def test_billing_down_at_the_swap_fails_the_step_and_settles(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, _ = await held_image(pipe, gauge, coll)
    gauge.fail_swap = 1
    await pipe.run(img)
    run = (await pipe.runs(img))["acme.blur"]
    assert (run.status.value, run.error_code) == ("failed", "storage_error")
    await assert_counted_once(pipe.db_state, gauge)
    assert (await pipe.row(img)).storage_bytes == (await pipe.row(img)).size_bytes


async def test_a_purge_with_a_swap_pending_releases_the_swapped_hold(
    pipe, blur, gauge, monkeypatch
):
    coll = await pipe.collection({"acme.blur": {}})
    img, _ = await held_image(pipe, gauge, coll)
    _crash_around_swap(monkeypatch, after=True)
    with pytest.raises(Crash):
        await pipe.run(img)
    await pipe.trash(Image, img, datetime.now(UTC) - timedelta(days=8))
    async with pipe.db_state.session_factory() as db:
        await purge_expired(db, pipe.store, now=datetime.now(UTC), grace_days=7)
        await finalize_session(db)
    await _settle(pipe)
    assert gauge.live() == []
    await assert_counted_once(pipe.db_state, gauge)


async def test_an_ingest_that_never_inserts_is_released(pipe, gauge):
    factory = pipe.db_state.session_factory
    slot = await hold_slot(factory, T, Slot(uuid.uuid4(), "k"), 100)
    assert [h.id for h in gauge.live()] == [slot.hold]
    assert await _settle(pipe) == 0  # the ingest still owns it
    await _settle(pipe, INGEST_CLAIM + timedelta(seconds=1))
    assert gauge.live() == [] and all(o.done_at for o in await ops(pipe.db_state))


async def test_concurrent_uploads_take_exactly_the_room(pipe, gauge):
    """No lease: billing's swap is the one atomic check, so four concurrent
    holds that interleave before billing decides still fit exactly the room."""
    factory = pipe.db_state.session_factory
    gauge.limit, gauge.delay = 250, 0.05
    slots = await asyncio.gather(
        *(hold_slot(factory, T, Slot(uuid.uuid4(), "k"), 100) for _ in range(4))
    )
    assert sorted(s.refused for s in slots) == [False, False, True, True]
    assert gauge.level == 200 <= gauge.limit
