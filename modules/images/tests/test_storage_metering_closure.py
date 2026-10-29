"""Nothing finishes an op without billing's terminal outcome for its key, and
the repair keeps at an image until it is counted right.

* The settler expires an op only after ``close_key`` answered; if billing
  cannot, the op stays unfinished and is retried.
* A refused repair swap is itself examined on the next lap and queued again
  until it lands (ordinary refusals used never to be looked at again).
* An expired shrink leaves the image named by an oversized hold: corrected.
* The scan's laps are bounded by the highest op id when they began, so they
  end under continuous arrivals, across gaps and a deleted top row; the
  cursor moves only by compare-and-set.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sm_images import billing, billing_ops, billing_repair
from sm_images.billing_settle import BACKOFF, OP_EXPIRED
from sm_images.models import BillingOp, BillingRepairCursor, Image
from sm_images.models.billing_op import OP_SWAP
from sm_images.tenancy import DEFAULT_TENANT as T
from sqlalchemy import delete, select, update

from tests.billing_support import assert_counted_once, held_image


async def _op(pipe, **values) -> int:
    async with pipe.db_state.session_factory() as s:
        row = BillingOp(**values)
        s.add(row)
        await s.commit()
        return row.id


def _done(**values) -> dict:
    return {"op": OP_SWAP, "done_at": datetime.now(UTC), **values}


async def _cursor(pipe) -> tuple[int, int | None]:
    async with pipe.db_state.session_factory() as s:
        row = (
            await s.execute(select(BillingRepairCursor.last_op_id, BillingRepairCursor.lap_end))
        ).one()
    return int(row[0]), row[1]


async def _repair_laps(pipe, laps: int = 3) -> None:
    for _ in range(laps):
        await billing_repair.repair(pipe.db_state.session_factory, T)


async def test_expiry_waits_for_billings_answer(pipe, gauge):
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll)
    past = datetime.now(UTC) - timedelta(seconds=1)
    await _op(pipe, op=OP_SWAP, image_id=img, quantity=1, idempotency_key="k",
              old_hold_id=seed, not_after=past)  # fmt: skip
    factory, gauge.fail_close = pipe.db_state.session_factory, 1
    assert await billing_ops.settle(factory, T) == 0  # billing down: not finished
    async with factory() as s:
        (op,) = (await s.execute(select(BillingOp))).scalars()
    assert (op.done_at, op.attempts) == (None, 1)
    later = datetime.now(UTC) + 2 * BACKOFF
    assert await billing_ops.settle(factory, T, now=later) == 1
    async with factory() as s:
        (op,) = (await s.execute(select(BillingOp))).scalars()
    assert (op.last_error, op.hold_id) == (OP_EXPIRED, None)  # closed: no hold
    late = await gauge.swap(T, billing.METER, seed, 1, "k", source=billing.SOURCE)
    assert type(late).__name__ == "Closed" and gauge.holds[seed].status == "committed"


async def test_a_refused_repair_swap_is_queued_again_until_it_lands(pipe, gauge):
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll)
    gauge.holds[seed] = gauge._set(gauge.holds[seed], "released")  # counted by nothing
    await _op(pipe, **_done(image_id=img, quantity=1, idempotency_key="lost",
                            last_error=OP_EXPIRED))  # fmt: skip
    gauge.limit = 0  # no room: the repair's swap is refused
    await _repair_laps(pipe, 1)
    refused = [o for o in await _ops(pipe) if o.last_error and "Quota" in o.last_error]
    assert len(refused) == 1 and refused[0].done_at is not None
    gauge.limit = None  # room again
    await _repair_laps(pipe)
    assert gauge.holds[(await pipe.row(img)).storage_hold_id].status == "committed"
    await assert_counted_once(pipe.db_state, gauge)


async def _ops(pipe) -> list:
    async with pipe.db_state.session_factory() as s:
        return list((await s.execute(select(BillingOp).order_by(BillingOp.id))).scalars())


async def test_an_expired_shrink_with_an_oversized_hold_is_corrected(pipe, gauge):
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll)
    size = (await pipe.row(img)).storage_bytes
    big = await gauge.swap(T, billing.METER, seed, 2 * size, "grow", source=billing.SOURCE)
    async with pipe.db_state.session_factory() as s:  # grown, then shrunk back to `size`
        await s.execute(update(Image).where(Image.id == img).values(storage_hold_id=big.id))
        await s.commit()
    past = datetime.now(UTC) - timedelta(seconds=1)
    await _op(pipe, op=OP_SWAP, image_id=img, quantity=size, idempotency_key="shrink",
              old_hold_id=big.id, not_after=past)  # fmt: skip
    factory = pipe.db_state.session_factory
    await billing_ops.settle(factory, T)  # expired: billing was down for a week
    await _repair_laps(pipe)
    row = await pipe.row(img)
    assert gauge.holds[row.storage_hold_id].quantity == size  # not the oversized hold
    await assert_counted_once(pipe.db_state, gauge)


async def test_laps_end_under_continuous_arrivals(pipe, gauge, monkeypatch):
    monkeypatch.setattr(billing_repair, "CAP", 2)
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll)
    busy, _ = await held_image(pipe, gauge, coll)
    size = (await pipe.row(img)).storage_bytes
    blocker = await _op(pipe, op=OP_SWAP, image_id=busy, quantity=1, claim_token="held",
                        claim_expires_at=datetime.now(UTC) + timedelta(hours=1))  # fmt: skip
    orphan = await gauge.swap(T, billing.METER, None, 1, "orphan", source="t")
    await _op(pipe, **_done(image_id=busy, hold_id=orphan.id, quantity=1))  # deferred
    factory = pipe.db_state.session_factory
    for tick in range(8):
        for _ in range(2):  # new healthy ops keep arriving, a full page a tick
            await _op(pipe, **_done(image_id=img, hold_id=seed, quantity=size))
        await billing_repair.repair(factory, T)
        if tick == 0:  # the blocker finishes: the deferred op can be decided now
            async with factory() as s:
                await s.execute(
                    update(BillingOp)
                    .where(BillingOp.id == blocker)
                    .values(done_at=datetime.now(UTC), claim_token=None)
                )
                await s.commit()
    assert gauge.holds[orphan.id].status == "released"  # revisited on a later lap


async def test_a_lap_ends_across_gaps_and_a_deleted_top_row(pipe, gauge, monkeypatch):
    monkeypatch.setattr(billing_repair, "CAP", 2)
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll)
    size = (await pipe.row(img)).storage_bytes
    ids = [await _op(pipe, **_done(image_id=img, hold_id=seed, quantity=size)) for _ in range(5)]
    factory = pipe.db_state.session_factory
    await billing_repair.repair(factory, T)
    assert await _cursor(pipe) == (ids[1], ids[4])
    async with factory() as s:  # a gap, and the lap's top row gone
        await s.execute(delete(BillingOp).where(BillingOp.id.in_([ids[2], ids[4]])))
        await s.commit()
    await billing_repair.repair(factory, T)
    assert await _cursor(pipe) == (0, None)  # the lap ended on a short page
    later = await _op(pipe, **_done(image_id=img, hold_id=seed, quantity=size))
    await billing_repair.repair(factory, T)  # a new lap, up to the new top
    async with factory() as s:
        unchecked = (await s.execute(select(BillingOp.id).where(billing_repair.candidate()))).all()
    assert unchecked == [] and later  # SQLite may reuse the deleted top id


async def test_a_stale_repair_never_moves_the_cursor_back(pipe, gauge, monkeypatch):
    from sm_images import billing_repair_cursor

    monkeypatch.setattr(billing_repair, "CAP", 2)
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll)
    size = (await pipe.row(img)).storage_bytes
    ids = [await _op(pipe, **_done(image_id=img, hold_id=seed, quantity=size)) for _ in range(6)]
    factory, real, state = pipe.db_state.session_factory, billing_repair_cursor.begin, {}

    async def stale(*args):
        lap = await real(*args)
        if not state:  # A has read the cursor; B runs two passes meanwhile
            state["A"] = lap
            await billing_repair.repair(factory, T)
            await billing_repair.repair(factory, T)
        return lap

    monkeypatch.setattr(billing_repair_cursor, "begin", stale)
    await billing_repair.repair(factory, T)  # A: its compare-and-set fails
    assert state["A"].last == 0
    assert await _cursor(pipe) == (ids[3], ids[5])  # where B left it
