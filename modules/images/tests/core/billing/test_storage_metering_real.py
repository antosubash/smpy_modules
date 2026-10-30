"""The storage gauge against billing's own tables (``usage_meter``, a worker's
view: no registry), and Codex's (v) expiry trace.

The (v) traces had an image counted by a hold that could lapse - a ``held``
reservation awaiting its commit, an expired rehold replacement - so its room
went to uploads and the tenant stored past its limit for good. Now every hold
images takes is committed by billing's swap: ingest, a grown hold whose
executor died after billing swapped it, the settler's takeover and its
correcting shrink leave no ``held`` row, billing's sweeper a year later
expires nothing, the gauge equals what the image stores, and the room left is
exactly the limit less that.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import finalize_session, init_db
from simple_module_db.listeners import attach_session_listeners
from sm_images.core import billing
from sm_images.core.billing import ops as billing_ops
from sm_images.core.billing import repair as billing_repair
from sm_images.core.errors import StorageQuotaExceeded
from sm_images.core.tenancy import DEFAULT_TENANT as T
from sm_images.ingest.slots import Slot, hold_slot, keep_hold
from sm_images.models import BillingOp, Collection, Image
from sm_images.models.billing_op import OP_SWAP
from sqlalchemy import select, update

LIMIT = 1000


@pytest.fixture
async def real(tmp_path, monkeypatch):
    from sm_billing.constants import PricingModel
    from sm_billing.models import Base, Plan, Subscription
    from sm_billing.plans import seed_default_plan
    from sm_images.models import Base as ImagesBase

    monkeypatch.setattr(billing, "billing_installed", lambda: True)
    state = init_db(f"sqlite+aiosqlite:///{tmp_path / 'billing.db'}")
    attach_session_listeners(state.sync_session_class)  # stamps the bound tenant
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(ImagesBase.metadata.create_all)
    await seed_default_plan(state.session_factory)
    async with state.session_factory() as s:
        plan = Plan(
            key="images", name="I", pricing_model=PricingModel.FLAT, limits={billing.METER: LIMIT}
        )
        s.add(plan)
        await s.flush()
        s.add(Subscription(tenant_id=T, plan_id=plan.id))
        await s.commit()
    yield state
    await state.engine.dispose()


async def _holds(factory) -> dict[str, tuple[str, int, object]]:
    from sm_billing.models import UsageHold

    async with factory() as s:
        rows = await s.execute(
            select(UsageHold.id, UsageHold.status, UsageHold.quantity, UsageHold.expires_at)
        )
        return {r[0]: (r[1], int(r[2]), r[3]) for r in rows}


async def _level(factory) -> int:
    from sm_billing.models import UsageGauge

    async with factory() as s:
        return int((await s.execute(select(UsageGauge.in_use))).scalar_one())


async def _ingest(factory, size: int) -> uuid.UUID:
    slot = await hold_slot(factory, T, Slot(uuid.uuid4(), "k"), size)
    async with factory() as db:
        coll = Collection(slug=f"c-{uuid.uuid4().hex[:6]}", name="C", owner_id="olga")
        db.add(coll)
        await db.flush()
        db.add(
            Image(
                id=slot.image_id,
                collection_id=coll.id,
                storage_key="k",
                filename="a.jpg",
                content_type="image/jpeg",
                size_bytes=size,
                storage_bytes=size,
                storage_hold_id=slot.hold,
            )
        )
        await keep_hold(db, slot.op, slot.hold)
        await finalize_session(db)
    return slot.image_id


async def test_codex_v_trace_no_images_hold_can_lapse(real):
    from sm_billing.metering.service import UsageService
    from sm_billing.metering.sweeper import expire_due

    factory = real.session_factory
    image = await _ingest(factory, 300)
    # A publication grew the image to 700: its executor wrote the op, billing
    # swapped, and the worker died before the image update.
    async with factory() as db:
        old = (await db.execute(select(Image.storage_hold_id))).scalar_one()
        key, claim = billing.hold_key(image, "grow"), timedelta(minutes=5)
        op = await billing_ops.open_op(db, OP_SWAP, image, 700, key, claim=claim, old=old)
        await finalize_session(db)
    grown = await billing.swap(factory, T, old, 700, op.key, not_after=op.not_after)
    assert await _level(factory) == 700  # counted once, by the swapped hold
    later = datetime.now(UTC) + timedelta(minutes=6)
    assert await billing_ops.settle(factory, T, now=later) >= 1  # takeover, then the shrink
    async with factory() as db:
        row = (await db.execute(select(Image.storage_hold_id, Image.storage_bytes))).one()
        pending = (await db.execute(select(BillingOp).where(BillingOp.done_at.is_(None)))).all()
    holds = await _holds(factory)
    assert pending == [] and holds[grown.id][0] == "released"
    assert holds[row[0]] == ("committed", 300, None)  # never held, so it cannot lapse
    assert not [h for h in holds.values() if h[0] == "held"]
    # A year on, billing's sweeper finds nothing to expire.
    clock = datetime.now(UTC) + timedelta(days=365)
    assert await expire_due(UsageService(factory, clock=lambda: clock)) == 0
    assert await _level(factory) == row[1] == 300
    # The room left is exactly the limit less what the image stores.
    assert (await hold_slot(factory, T, Slot(uuid.uuid4(), "k"), LIMIT - 300 + 1)).refused
    assert not (await hold_slot(factory, T, Slot(uuid.uuid4(), "k"), LIMIT - 300)).refused


async def test_codex_trace_t_against_real_billing(real):
    """The executor's call is delayed past its claim; the takeover's swap is
    refused and the op finished; room comes back; the delayed call lands with
    the same key - and billing answers the same refusal, changing nothing."""
    from sm_billing.models import Plan

    factory = real.session_factory
    image = await _ingest(factory, 900)
    async with factory() as db:
        old = (await db.execute(select(Image.storage_hold_id))).scalar_one()
        key, claim = billing.hold_key(image, "grow"), timedelta(minutes=5)
        op = await billing_ops.open_op(db, OP_SWAP, image, 1200, key, claim=claim, old=old)
        await finalize_session(db)
    later = datetime.now(UTC) + timedelta(minutes=6)
    assert await billing_ops.settle(factory, T, now=later) == 1  # the takeover: refused
    async with factory() as s:  # room again
        plan = (await s.execute(select(Plan).where(Plan.key == "images"))).scalar_one()
        plan.limits = {billing.METER: 5000}
        await s.commit()
    with pytest.raises(StorageQuotaExceeded):  # the delayed call: the key's outcome
        await billing.swap(factory, T, old, 1200, key, not_after=op.not_after)
    holds = await _holds(factory)
    assert holds[old][:2] == ("committed", 900) and await _level(factory) == 900
    assert sorted(h[0] for h in holds.values()) == ["committed", "refused"]


async def test_codex_p1_2_an_early_expiry_closes_the_key(real):
    """Images' clock is past an op's deadline while the database's is not, so
    its settler expires an op billing would still admit, and the repair then
    finds the image counted. The expiry closed the key first: the paused
    executor's late swap under it writes nothing, instead of releasing the
    image's hold after the op was finished and examined."""
    factory = real.session_factory
    image = await _ingest(factory, 300)
    async with factory() as db:
        old = (await db.execute(select(Image.storage_hold_id))).scalar_one()
        key, claim = billing.hold_key(image, "grow"), timedelta(minutes=5)
        op = await billing_ops.open_op(db, OP_SWAP, image, 700, key, claim=claim, old=old)
        await finalize_session(db)
    soon, lapsed = datetime.now(UTC) + timedelta(seconds=30), datetime.now(UTC)
    async with factory() as db:  # its deadline is near, and the executor's claim lapsed
        await db.execute(
            update(BillingOp)
            .where(BillingOp.id == op.op_id)
            .values(not_after=soon, claim_expires_at=lapsed)
        )
        await finalize_session(db)
    ahead = soon + timedelta(seconds=2)  # images' clock: 2 s past the deadline
    assert await billing_ops.settle(factory, T, now=ahead) == 1
    assert await billing_repair.repair(factory, T) == 0  # counted right: nothing to do
    with pytest.raises(billing.SwapExpired):  # the executor's late call: Closed
        await billing.swap(factory, T, old, 700, key, not_after=soon)
    holds = await _holds(factory)
    assert holds[old][:2] == ("committed", 300) and await _level(factory) == 300
    assert sorted(h[0] for h in holds.values()) == ["closed", "committed"]
