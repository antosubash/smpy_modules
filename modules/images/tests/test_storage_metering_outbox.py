"""The storage gauge's durable settlement outbox (``sm_images.billing_ops``)
and the reservation's deadline at the fenced completion.

A failed commit never lets the old hold go, a lapsed new hold is re-held for
the image's current total before the old one is released, a failed release is
retried by reconcile, and a reservation that lapsed is refused under the lock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import finalize_session
from sm_images import billing_ops
from sm_images.janitor import purge_expired
from sm_images.models import Image
from sm_images.reconcile import reconcile_tenant
from sm_images.tenancy import DEFAULT_TENANT

from tests.billing_support import held_image, ops
from tests.pipeline_support import Blur, use_steps

T = DEFAULT_TENANT
LATER = timedelta(hours=2)


@pytest.fixture
def blur():
    step = Blur()
    use_steps(step)
    return step


async def test_a_failed_commit_keeps_the_old_hold_until_it_lands(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed = await held_image(pipe, gauge, coll)
    gauge.fail_commit = 1
    await pipe.run(img)
    row = await pipe.row(img)
    assert row.display_key is not None and row.storage_hold_id != seed
    assert gauge.holds[seed].status == "committed"  # never released before the commit
    commit, release = await ops(pipe.db_state)
    assert (commit.op, commit.done_at, commit.attempts) == ("commit", None, 1)
    assert "billing is down" in commit.last_error
    assert (release.op, release.after_id, release.done_at) == ("release", commit.id, None)

    assert await billing_ops.settle(pipe.db_state.session_factory, T) == 0  # backing off
    settled = await billing_ops.settle(
        pipe.db_state.session_factory, T, now=datetime.now(UTC) + LATER
    )
    assert settled == 2
    assert gauge.holds[row.storage_hold_id].status == "committed"
    assert gauge.holds[seed].status == "released"
    assert all(o.done_at for o in await ops(pipe.db_state))


async def test_a_lapsed_new_hold_is_reheld_before_the_old_is_released(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}, "renditions": {}})
    img, seed = await held_image(pipe, gauge, coll)
    gauge.expire_on_commit = 1  # the display copy's hold lapses before its commit
    await pipe.run(img)
    row = await pipe.row(img)
    (live,) = gauge.live()
    assert (live.id, live.status, live.quantity) == (
        row.storage_hold_id,
        "committed",
        row.storage_bytes,
    )
    reheld = [k for k, v in gauge.keys.items() if "rehold-" in k]
    assert len(reheld) == 1
    assert gauge.holds[seed].status == "released"
    calls = [c[:2] for c in gauge.calls]
    rehold_id = gauge.keys[reheld[0]]
    assert calls.index(("release", seed)) > calls.index(("commit", rehold_id))
    assert all(o.done_at for o in await ops(pipe.db_state))


async def test_a_rehold_never_overwrites_a_newer_hold(pipe, blur, gauge):
    """The image moved on before the rehold ran: its fresh hold is given back."""
    coll = await pipe.collection({"acme.blur": {}})
    img, seed = await held_image(pipe, gauge, coll)
    gauge.fail_commit = 1
    await pipe.run(img)
    lapsed = (await pipe.row(img)).storage_hold_id
    gauge.expire(lapsed)
    async with pipe.db_state.session_factory() as s:  # a newer publication's hold
        newer = await gauge.reserve(T, "images.storage_bytes", 1, "newer", source="t")
        await gauge.commit(newer.id)
        row = await s.get(Image, img)
        row.storage_hold_id = newer.id
        await s.commit()
    await billing_ops.settle(pipe.db_state.session_factory, T, now=datetime.now(UTC) + LATER)
    assert (await pipe.row(img)).storage_hold_id == newer.id
    assert gauge.holds[newer.id].status == "committed"
    assert gauge.holds[seed].status == "released"
    assert [h.id for h in gauge.live()] == [newer.id]


async def test_a_failed_replacement_release_is_retried(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed = await held_image(pipe, gauge, coll)
    gauge.fail_release = 1
    await pipe.run(img)
    assert gauge.holds[seed].status == "committed"
    pending = [o for o in await ops(pipe.db_state) if o.done_at is None]
    assert [(o.op, o.hold_id, o.attempts) for o in pending] == [("release", seed, 1)]
    await billing_ops.settle(pipe.db_state.session_factory, T, now=datetime.now(UTC) + LATER)
    assert gauge.holds[seed].status == "released"


async def test_a_failed_purge_release_is_retried_by_reconcile(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, _ = await held_image(pipe, gauge, coll)
    await pipe.run(img)
    held = (await pipe.row(img)).storage_hold_id
    await pipe.trash(Image, img, datetime.now(UTC) - timedelta(days=8))
    gauge.fail_release = 1
    async with pipe.db_state.session_factory() as db:
        await purge_expired(db, pipe.store, now=datetime.now(UTC), grace_days=7)
        await finalize_session(db)
    assert gauge.holds[held].status == "committed"  # the failure is not forgotten
    (op,) = [o for o in await ops(pipe.db_state) if o.done_at is None]
    assert (op.op, op.hold_id, op.image_id) == ("release", held, img)
    done = await reconcile_tenant(pipe.runtime, T, datetime.now(UTC) + LATER)
    assert done["billing_ops"] == 1
    assert gauge.holds[held].status == "released"


async def test_the_reservation_outlives_the_step_lease(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, _ = await held_image(pipe, gauge, coll)
    await pipe.run(img)
    asked = [t for t in gauge.ttls if t is not None]
    assert asked and min(asked) >= pipe.settings.step_lease_seconds


async def test_a_reservation_near_its_deadline_is_extended(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, _ = await held_image(pipe, gauge, coll)
    gauge.next_seconds = [30]  # inside the renewal margin
    await pipe.run(img)
    held = (await pipe.row(img)).storage_hold_id
    assert ("extend", held) in [c[:2] for c in gauge.calls]
    assert gauge.holds[held].status == "committed"


async def test_a_lapsed_reservation_is_refused_under_the_lock(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed = await held_image(pipe, gauge, coll)
    gauge.next_seconds = [0]  # lapsed before the completion; extend fails too
    await pipe.run(img)  # refused, requeued, published by the next attempt
    row = await pipe.row(img)
    first = gauge.keys[next(k for k in gauge.keys if k not in ("seed",))]
    assert first != row.storage_hold_id and gauge.holds[first].status not in ("held", "committed")
    assert [h.id for h in gauge.live()] == [row.storage_hold_id]
    assert gauge.holds[seed].status == "released"
