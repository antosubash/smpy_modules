"""The repair of a lost swap is serialised per image, scans every candidate,
and an op too old to call billing is expired rather than run.

* Race R: a repair decides from reads taken outside any lock that an orphan
  hold H is spare (the image's own hold counts), and stalls. Meanwhile the
  image's hold stops counting and a second repair installs H. The first then
  acts on its stale decision. Every install-or-release decision is now taken
  under the image's row lock, re-reading the hold it names and its unfinished
  ops, and a release is recorded as a ``release`` op in that transaction.
* Starvation: more than a page of newer candidates must not hide an older one.
* T30: billing keeps a key's outcome 30 days after it settles; images never
  calls billing for an op older than ``BILLING_OP_MAX_AGE`` (7 days). Such an
  op is finished ``op_expired``, and the repair makes sure its image is counted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sm_images.core import billing
from sm_images.core.billing import ops as billing_ops
from sm_images.core.billing import repair as billing_repair
from sm_images.core.billing.settle import BILLING_OP_MAX_AGE, OP_EXPIRED
from sm_images.core.tenancy import DEFAULT_TENANT as T
from sm_images.models import BillingOp
from sm_images.models.billing_op import OP_SWAP
from sqlalchemy import select, update

from tests.support.billing import assert_counted_once, held_image

LOST = "images:{}:storage:lost"


async def _done_op(pipe, img, hold_id, qty, **kw):
    async with pipe.db_state.session_factory() as s:
        s.add(
            BillingOp(
                op=OP_SWAP,
                image_id=img,
                hold_id=hold_id,
                quantity=qty,
                idempotency_key=kw.pop("key", LOST.format(uuid.uuid4().hex)),
                done_at=datetime.now(UTC),
                **kw,
            )
        )
        await s.commit()


async def test_race_r_a_stale_repair_never_releases_what_another_installed(
    pipe, gauge, monkeypatch
):
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll)
    size = (await pipe.row(img)).storage_bytes
    orphan = await gauge.swap(T, billing.METER, None, size, "lost", source=billing.SOURCE)
    await _done_op(pipe, img, orphan.id, size, key="lost")
    factory, real, state = pipe.db_state.session_factory, billing_repair._decide, {}

    async def stall(*args, **kwargs):
        if not state:  # the first repair has decided "the image is counted": it stalls
            state["stalled"] = True
            gauge.holds[seed] = gauge._set(gauge.holds[seed], "released")
            assert await billing_repair.repair(factory, T) == 1  # installs the orphan
        return await real(*args, **kwargs)

    monkeypatch.setattr(billing_repair, "_decide", stall)
    await billing_repair.repair(factory, T)
    row = await pipe.row(img)
    assert row.storage_hold_id == orphan.id
    assert gauge.holds[orphan.id].status == "committed"  # never released under the image
    await assert_counted_once(pipe.db_state, gauge)


async def test_no_page_of_newer_candidates_starves_an_older_one(pipe, gauge):
    coll = await pipe.collection({})
    img, _seed = await held_image(pipe, gauge, coll)
    size = (await pipe.row(img)).storage_bytes
    orphan = await gauge.swap(T, billing.METER, None, size, "lost", source=billing.SOURCE)
    await _done_op(pipe, img, orphan.id, size, key="lost")  # the oldest candidate
    for _ in range(150):  # newer candidates: holds of images long gone, released
        gone = await gauge.swap(T, billing.METER, None, 1, uuid.uuid4().hex, source="t")
        await gauge.release(gone.id)
        await _done_op(pipe, uuid.uuid4(), gone.id, 1)
    factory = pipe.db_state.session_factory
    assert await billing_repair.repair(factory, T) == 1
    assert gauge.holds[orphan.id].status == "released"  # the image's own hold counts
    for _ in range(3):
        await billing_repair.repair(factory, T)
    async with factory() as s:
        unchecked = (await s.execute(select(BillingOp.id).where(billing_repair.candidate()))).all()
    assert unchecked == []  # every candidate examined once
    await assert_counted_once(pipe.db_state, gauge)


async def test_t30_an_op_older_than_the_bound_is_expired_not_run(pipe, gauge):
    """An op past ``BILLING_OP_MAX_AGE`` never reaches billing (whose key
    outcomes are kept 30 days); the repair then sees its image counted."""
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll)
    gauge.holds[seed] = gauge._set(gauge.holds[seed], "released")  # the lost swap's mark
    old = datetime.now(UTC) - BILLING_OP_MAX_AGE - timedelta(hours=1)
    factory = pipe.db_state.session_factory
    async with factory() as s:
        s.add(BillingOp(op=OP_SWAP, image_id=img, quantity=1, idempotency_key="stale"))
        await s.commit()
        await s.execute(update(BillingOp).values(created_at=old))
        await s.commit()
    await billing_ops.settle(factory, T)
    async with factory() as s:
        (op,) = (await s.execute(select(BillingOp))).scalars()
    assert (op.done_at is not None, op.last_error) == (True, OP_EXPIRED)
    assert not [c for c in gauge.calls if c[0] == "swap" and c[3] == "stale"]
    assert await billing_repair.repair(factory, T) == 1  # the image counted nothing
    row = await pipe.row(img)
    assert gauge.holds[row.storage_hold_id].status == "committed"
    await assert_counted_once(pipe.db_state, gauge)
