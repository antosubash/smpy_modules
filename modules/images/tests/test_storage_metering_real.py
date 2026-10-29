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
from sm_images import billing, billing_ops
from sm_images.ingest.slots import Slot, hold_slot, keep_hold
from sm_images.models import BillingOp, Collection, Image
from sm_images.models.billing_op import OP_SWAP
from sm_images.tenancy import DEFAULT_TENANT as T
from sqlalchemy import select

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
        op = await billing_ops.open_op(
            db, OP_SWAP, image, 700, billing.hold_key(image, "grow"), claim=timedelta(minutes=5)
        )
        await finalize_session(db)
    async with factory() as db:
        old = (await db.execute(select(Image.storage_hold_id))).scalar_one()
    grown = await billing.swap(factory, T, old, 700, op.key)
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
