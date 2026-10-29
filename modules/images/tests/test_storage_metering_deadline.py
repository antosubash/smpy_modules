"""Billing enforces each op's deadline; expiry never forgets committed work; the
sweep and the repair scan never lose a candidate.

* Codex's delayed-executor trace (T30): the executor pauses just before its
  billing call; a settler takes the op over, billing refuses it, the op is
  finished; 30 days pass and billing's retention purges the refusal; the
  executor resumes. Billing refuses the call itself - it is past the op's
  ``not_after`` - so no hold is created that nothing could install.
* An op expired after billing swapped it, before anything recorded the hold:
  the key's outcome (``get_hold_by_key``) is kept on the op, and the repair
  installs it.
* The sweep's predicate is NULL-safe; the repair's scan has a cursor, so a page
  of deferred candidates does not block the ones after it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_images import billing, billing_ops, billing_repair
from sm_images.billing_settle import CLAIM, OP_EXPIRED
from sm_images.models import BillingOp
from sm_images.models.billing_op import OP_RELEASE, OP_SWAP
from sm_images.pipeline import storage_hold
from sm_images.tenancy import DEFAULT_TENANT as T
from sqlalchemy import select

from tests.billing_support import assert_counted_once, held_image
from tests.pipeline_support import Blur, use_steps

LATER = CLAIM + timedelta(seconds=1)


@pytest.fixture
def blur():
    step = Blur()
    use_steps(step)
    return step


async def _op(pipe, **values) -> int:
    async with pipe.db_state.session_factory() as s:
        row = BillingOp(**values)
        s.add(row)
        await s.commit()
        return row.id


async def test_codex_t30_a_delayed_executor_creates_no_hold(pipe, blur, gauge, monkeypatch):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed = await held_image(pipe, gauge, coll)
    real, state = billing.swap, {"armed": True}

    async def delayed(*args, **kwargs):
        if state.pop("armed", False):  # the executor, paused before its billing call
            gauge.limit = gauge.level
            now = datetime.now(UTC) + LATER
            assert await billing_ops.settle(pipe.db_state.session_factory, T, now=now) == 1
            gauge.limit = None
            gauge.forget(args[4])  # 30 days on, retention purged the refusal
            gauge.later = timedelta(days=30)
        return await real(*args, **kwargs)

    monkeypatch.setattr(storage_hold.billing, "swap", delayed)
    await pipe.run(img)
    run = (await pipe.runs(img))["acme.blur"]
    assert (run.status.value, run.error_code) == ("failed", "storage_error")
    assert (await pipe.row(img)).storage_hold_id == seed
    assert [h.id for h in gauge.live()] == [seed]  # no hold nothing could install
    await assert_counted_once(pipe.db_state, gauge)


async def test_an_expired_op_keeps_the_hold_its_key_made(pipe, gauge):
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll)
    size = (await pipe.row(img)).storage_bytes
    key = billing.hold_key(img, "late")
    past = datetime.now(UTC) - timedelta(seconds=1)
    await _op(pipe, op=OP_SWAP, image_id=img, quantity=size, idempotency_key=key,
              old_hold_id=seed, not_after=past)  # fmt: skip
    landed = await gauge.swap(T, billing.METER, seed, size, key, source=billing.SOURCE)
    factory = pipe.db_state.session_factory
    await billing_ops.settle(factory, T)  # past its deadline: expired, nothing called
    async with factory() as s:
        (op,) = (await s.execute(select(BillingOp))).scalars()
    assert (op.last_error, op.hold_id) == (OP_EXPIRED, landed.id)  # the key's outcome kept
    assert await billing_repair.repair(factory, T) == 1
    assert (await pipe.row(img)).storage_hold_id == landed.id
    await assert_counted_once(pipe.db_state, gauge)


async def test_the_sweep_keeps_exactly_what_the_repair_needs(pipe, gauge):
    done, img = datetime.now(UTC) - timedelta(days=30), uuid.uuid4()
    base = {"image_id": img, "done_at": done, "quantity": 1}
    plain = await _op(pipe, op=OP_SWAP, **base)  # NULL hold and error: nothing to repair
    expired = await _op(pipe, op=OP_SWAP, last_error=OP_EXPIRED, **base)
    holding = await _op(pipe, op=OP_SWAP, hold_id="h1", **base)
    examined = await _op(pipe, op=OP_SWAP, hold_id="h2", repaired_at=done, **base)
    released = await _op(pipe, op=OP_RELEASE, hold_id="h3", **base)
    factory = pipe.db_state.session_factory
    assert await billing_ops.sweep(factory, T, datetime.now(UTC)) == 3
    async with factory() as s:
        kept = set((await s.execute(select(BillingOp.id))).scalars())
    assert kept == {expired, holding}
    assert {plain, examined, released}.isdisjoint(kept)


async def test_the_scan_moves_past_a_page_of_deferred_candidates(pipe, gauge):
    factory = pipe.db_state.session_factory
    coll = await pipe.collection({})
    busy, _ = await held_image(pipe, gauge, coll)
    await _op(pipe, op=OP_SWAP, image_id=busy, quantity=1, claim_token="held",
              claim_expires_at=datetime.now(UTC) + timedelta(hours=1))  # fmt: skip
    for i in range(billing_repair.CAP):  # deferred: their image has an op unfinished
        spare = await gauge.swap(T, billing.METER, None, 1, f"spare-{i}", source="t")
        await _op(pipe, op=OP_SWAP, image_id=busy, hold_id=spare.id, quantity=1,
                  done_at=datetime.now(UTC))  # fmt: skip
    other, _ = await held_image(pipe, gauge, coll)
    orphan = await gauge.swap(T, billing.METER, None, 1, "orphan", source="t")
    await _op(pipe, op=OP_SWAP, image_id=other, hold_id=orphan.id, quantity=1,
              done_at=datetime.now(UTC))  # fmt: skip
    assert await billing_repair.repair(factory, T) == 0  # a page of deferrals
    assert await billing_repair.repair(factory, T) == 1  # the next one is reached
    assert gauge.holds[orphan.id].status == "released"
