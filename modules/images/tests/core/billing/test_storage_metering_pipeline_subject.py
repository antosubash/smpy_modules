"""Pipeline growth bills the subject the image's hold was taken under (#284).

A first hold bills the collection's owner (``Loaded.subject``, in billing's
``user`` mode); an existing hold keeps its recorded subject
(``Image.storage_subject``, ``NULL`` meaning the tenant) across a mode switch
or an ownership change. The fake gauge scopes holds per subject, so a swap
under any other subject raises ``HoldNotFound`` and fails these tests.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from sm_images.core.billing import ops as billing_ops
from sm_images.core.billing import subject
from sm_images.core.tenancy import DEFAULT_TENANT as T
from sm_images.pipeline.orchestrate import rerun_image

from tests.core.billing.test_storage_metering_swap import Sized
from tests.support.billing import assert_counted_once, held_image, no_settle, ops
from tests.support.pipeline import Blur, use_steps


@pytest.fixture
def blur():
    step = Blur()
    use_steps(step)
    return step


@pytest.fixture
def owner(pipe, user_mode) -> str:
    """Billing's ``user`` mode on the pipeline's runtime; a fresh owner id."""
    pipe.runtime = user_mode.runtime(pipe.runtime)
    return str(uuid.uuid4())


async def _owned(pipe, owner: str, steps=None):
    return await pipe.collection(steps or {"acme.blur": {}, "renditions": {}}, owner_id=owner)


async def test_growth_first_hold_in_user_mode_bills_owner(pipe, blur, gauge, owner):
    coll = await _owned(pipe, owner)
    img = await pipe.image(coll)
    await pipe.run(img)
    (hold,) = gauge.live()
    row = await pipe.row(img)
    assert hold.tenant_id == f"user:{owner}"
    assert (row.storage_hold_id, row.storage_subject) == (hold.id, f"user:{owner}")
    assert gauge.level_of(T) == 0
    assert {o.subject for o in await ops(pipe.db_state)} == {f"user:{owner}"}
    await assert_counted_once(pipe.db_state, gauge)


async def test_growth_keeps_legacy_tenant_hold_after_switch(pipe, blur, gauge, owner):
    coll = await _owned(pipe, owner)
    img, seed = await held_image(pipe, gauge, coll)  # NULL subject: the tenant's
    await pipe.run(img)
    (hold,) = gauge.live()
    assert hold.id != seed and hold.tenant_id == T
    assert gauge.level_of(f"user:{owner}") == 0
    assert (await pipe.row(img)).storage_subject == T
    await assert_counted_once(pipe.db_state, gauge)


async def test_growth_keeps_user_hold_after_owner_change(pipe, blur, gauge, owner):
    a = f"user:{uuid.uuid4()}"
    coll = await _owned(pipe, owner)  # the owner is ``owner``; the hold is ``a``'s
    img, seed = await held_image(pipe, gauge, coll, subject=a)
    await pipe.run(img)
    (hold,) = gauge.live()
    assert hold.id != seed and hold.tenant_id == a
    assert gauge.level_of(f"user:{owner}") == 0
    assert (await pipe.row(img)).storage_subject == a
    await assert_counted_once(pipe.db_state, gauge)


async def test_shrink_queues_swap_under_held_subject(pipe, gauge, owner, monkeypatch):
    step = Sized((96, 72))
    use_steps(step)
    a = f"user:{uuid.uuid4()}"
    coll = await _owned(pipe, owner, {"acme.blur": {}})
    img, _ = await held_image(pipe, gauge, coll, subject=a)
    await pipe.run(img)
    step.dims = (8, 6)
    with monkeypatch.context() as later:  # the shrink waits: read it as queued
        later.setattr(billing_ops, "settle", no_settle)
        await rerun_image(pipe.runtime, T, img, "force")
    (shrink,) = [o for o in await ops(pipe.db_state) if o.done_at is None]
    assert shrink.subject == a == (await pipe.row(img)).storage_subject
    await billing_ops.settle(pipe.db_state.session_factory, T)
    assert {h.tenant_id for h in gauge.live()} == {a}
    await assert_counted_once(pipe.db_state, gauge)


async def test_worker_mode_user_meters_owner(pipe, blur, gauge, user_mode, monkeypatch):
    import sm_billing.contracts as contracts

    monkeypatch.setattr(contracts, "worker_subject_mode", lambda: "user")
    pipe.runtime = dataclasses.replace(pipe.runtime, subject_mode=subject.worker_mode)
    owner = str(uuid.uuid4())
    coll = await _owned(pipe, owner)
    img = await pipe.image(coll)
    await pipe.run(img)
    (hold,) = gauge.live()
    assert hold.tenant_id == f"user:{owner}"
    await assert_counted_once(pipe.db_state, gauge)


async def test_loaded_and_staging_carry_the_owner(pipe, gauge, owner, monkeypatch):
    """What an AI step bills (Task 7 reads ``Staging.subject``)."""
    from sm_images.pipeline import executor

    seen = []
    real = executor.Staging

    def spy(settings):
        staging = real(settings)
        seen.append(staging)
        return staging

    monkeypatch.setattr(executor, "Staging", spy)
    step = Blur()
    use_steps(step)
    coll = await _owned(pipe, owner, {"acme.blur": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    assert seen and all(s.subject == f"user:{owner}" for s in seen)


async def test_tenant_mode_loads_no_owner(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    (hold,) = gauge.live()
    assert hold.tenant_id == T
    assert (await pipe.row(img)).storage_subject == T


async def test_deleted_owner_bills_tenant(pipe, blur, gauge, owner, monkeypatch):
    async def gone(db, who):
        return False

    monkeypatch.setattr(subject, "user_exists", gone)  # the owner's user row is gone
    coll = await _owned(pipe, owner)
    img = await pipe.image(coll)
    await pipe.run(img)
    (hold,) = gauge.live()
    assert hold.tenant_id == T
    await assert_counted_once(pipe.db_state, gauge)
