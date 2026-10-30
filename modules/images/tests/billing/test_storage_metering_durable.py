"""A swap's outcome is durable per key, and an orphaned swap is repaired.

* Codex's trace T: the executor's billing call is delayed past its claim; a
  settler takes the op over and billing refuses its swap (the gauge was full),
  so the op is finished as refused. Room comes back, and the executor's
  delayed call - the same key - lands. Billing must answer it with the same
  refusal: were it a fresh swap, the image's hold would be released under an
  image that still names it, and the new hold would be named by nothing.
* A done op whose hold billing reports committed, but which the image does not
  name (the image lost its claim with a committed swap): reconcile repairs it -
  installs it where the image still names a hold that no longer counts, and
  releases it where the image is counted already or gone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_images import billing
from sm_images.billing import ops as billing_ops
from sm_images.billing import repair as billing_repair
from sm_images.billing.settle import CLAIM
from sm_images.models import BillingOp, Image
from sm_images.models.billing_op import OP_SWAP
from sm_images.pipeline import storage_hold
from sm_images.tenancy import DEFAULT_TENANT as T
from sqlalchemy import delete

from tests.support.billing import assert_counted_once, held_image
from tests.support.pipeline import Blur, use_steps

LATER = CLAIM + timedelta(seconds=1)


@pytest.fixture
def blur():
    step = Blur()
    use_steps(step)
    return step


def _settle(pipe):
    return billing_ops.settle(pipe.db_state.session_factory, T, now=datetime.now(UTC) + LATER)


async def test_codex_trace_t_a_refusal_is_final_for_its_key(pipe, blur, gauge, monkeypatch):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed = await held_image(pipe, gauge, coll)
    real, state = billing.swap, {"armed": True}

    async def delayed(*args, **kwargs):
        if state.pop("armed", False):  # the executor's call, held up past its claim
            gauge.limit = gauge.level  # full: the takeover's swap is refused
            assert await _settle(pipe) == 1
            gauge.limit = None  # room again before the delayed call lands
        return await real(*args, **kwargs)

    monkeypatch.setattr(storage_hold.billing, "swap", delayed)
    await pipe.run(img)
    run = (await pipe.runs(img))["acme.blur"]
    assert (run.status.value, run.error_code) == ("failed", "quota_exceeded")
    row = await pipe.row(img)
    assert (row.display_key, row.storage_hold_id) == (None, seed)
    assert [h.id for h in gauge.live()] == [seed]
    await assert_counted_once(pipe.db_state, gauge)


async def _orphan(pipe, gauge, img, *, release_named: bool) -> str:
    """A done swap op whose committed hold the image does not name."""
    row = await pipe.row(img)
    hold = await gauge.swap(
        T,
        billing.METER,
        row.storage_hold_id if release_named else None,
        row.storage_bytes,
        f"images:{img}:storage:lost",
        source=billing.SOURCE,
    )
    async with pipe.db_state.session_factory() as s:
        s.add(
            BillingOp(
                op=OP_SWAP,
                image_id=img,
                hold_id=hold.id,
                quantity=row.storage_bytes,
                idempotency_key=f"images:{img}:storage:lost",
                done_at=datetime.now(UTC),
            )
        )
        await s.commit()
    return hold.id


async def test_an_image_naming_a_released_hold_gets_the_committed_swap(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed = await held_image(pipe, gauge, coll)
    lost = await _orphan(pipe, gauge, img, release_named=True)
    assert gauge.holds[seed].status == "released"  # the image names a hold counting nothing
    fixed = await billing_repair.repair(pipe.db_state.session_factory, T)
    assert fixed == 1 and (await pipe.row(img)).storage_hold_id == lost
    await assert_counted_once(pipe.db_state, gauge)


async def test_an_orphan_beside_a_counted_image_is_released(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed = await held_image(pipe, gauge, coll)
    lost = await _orphan(pipe, gauge, img, release_named=False)
    assert gauge.level == 2 * (await pipe.row(img)).storage_bytes  # counted twice
    assert await billing_repair.repair(pipe.db_state.session_factory, T) == 1
    assert gauge.holds[lost].status == "released"
    assert (await pipe.row(img)).storage_hold_id == seed
    await assert_counted_once(pipe.db_state, gauge)


async def test_an_orphan_of_a_gone_image_is_released(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, _seed = await held_image(pipe, gauge, coll)
    await _orphan(pipe, gauge, img, release_named=True)
    async with pipe.db_state.session_factory() as s:  # hard-deleted, as the purge leaves it
        await s.execute(delete(Image).where(Image.id == img))
        await s.commit()
    assert await billing_repair.repair(pipe.db_state.session_factory, T) == 1
    assert gauge.live() == []


async def test_a_healthy_tenant_costs_only_billing_reads(pipe, blur, gauge):
    """The repair verifies each op's image against billing (its named hold may
    have been released since), but a healthy tenant gets reads, no writes."""
    coll = await pipe.collection({"acme.blur": {}})
    img, _ = await held_image(pipe, gauge, coll)
    await pipe.run(img)
    calls = len(gauge.calls)
    assert await billing_repair.repair(pipe.db_state.session_factory, T) == 0
    assert {c[0] for c in gauge.calls[calls:]} <= {"get_hold"}
    await assert_counted_once(pipe.db_state, gauge)
