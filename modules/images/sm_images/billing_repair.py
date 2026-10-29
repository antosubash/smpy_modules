"""The backstop for a swap the image never took (run by ``images.reconcile``).

A done ``swap`` or ``ingest`` op records the hold billing gave it. Normally the
image names that hold (the op installed it) or billing released it (a later
swap replaced it, the image is gone, the op released it). If neither - billing
reports the op's hold **committed** while the image names another, with no
swap of the image pending - the image lost a committed swap, and it is
reconciled (:func:`repair`):

* the image names a hold that no longer counts (released, or none) → the
  committed hold is written onto it, compare-and-set on what it named, and a
  correcting swap is queued when its size differs from ``storage_bytes``;
* the image is counted by another committed hold already, or is gone → the
  orphan is released.

So an image is never left naming a released hold while a hold of its own is
committed beside it. Only each image's newest done op with a hold, done within
:data:`WINDOW`, is looked at, and only where the image does not name its hold:
a healthy tenant costs one query and no billing read. At most :data:`CAP`
images per call.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.orm import aliased

from sm_images import billing, billing_ops
from sm_images.billing_install import release_hold
from sm_images.models import BillingOp, Image
from sm_images.models.billing_op import OP_INGEST, OP_SWAP

__all__ = ["CAP", "WINDOW", "repair"]

logger = logging.getLogger(__name__)
WINDOW = timedelta(days=1)
CAP = 100
_COMMITTED = "committed"


def _suspects(tenant: str, since: datetime) -> Any:
    newest = (
        select(func.max(BillingOp.id))
        .where(
            BillingOp.tenant_id == tenant,
            BillingOp.op.in_((OP_SWAP, OP_INGEST)),
            BillingOp.hold_id.is_not(None),
            BillingOp.image_id.is_not(None),
            BillingOp.done_at >= since,
        )
        .group_by(BillingOp.image_id)
    )
    pending = aliased(BillingOp)
    queued = exists().where(
        pending.tenant_id == tenant,
        pending.image_id == BillingOp.image_id,
        pending.op == OP_SWAP,
        pending.done_at.is_(None),
    )
    image = and_(Image.id == BillingOp.image_id, Image.tenant_id == tenant)
    return (
        select(BillingOp.image_id, BillingOp.hold_id, Image.id, Image.storage_hold_id)
        .outerjoin(Image, image)
        .where(
            BillingOp.id.in_(newest),
            ~queued,
            or_(Image.id.is_(None), Image.storage_hold_id.is_distinct_from(BillingOp.hold_id)),
        )
        .order_by(BillingOp.id.desc())
        .limit(CAP)
        .execution_options(include_deleted=True)
    )


async def repair(factory: Any, tenant: str, now: datetime | None = None) -> int:
    """Reconcile the tenant's images that lost a committed swap; how many."""
    meter = billing.storage_meter(factory)
    if meter is None:
        return 0
    since = (now or datetime.now(UTC)) - WINDOW
    async with factory() as db:
        rows = (await db.execute(_suspects(tenant, since))).all()
        await finalize_session(db)
    fixed = 0
    for image_id, hold_id, present, named in rows:
        orphan = await meter.get_hold(tenant, hold_id)
        if orphan is None or orphan.status != _COMMITTED:
            continue  # released or replaced since: nothing lost
        counted = named is not None and await _committed(meter, tenant, named)
        if present is None or counted:
            await release_hold(meter, hold_id)
        elif not await _install(factory, tenant, image_id, named, hold_id, orphan.quantity):
            continue  # the image moved on meanwhile: the next pass looks again
        logger.warning("images.billing_repair image=%s hold=%s", image_id, hold_id)
        fixed += 1
    return fixed


async def _committed(meter: Any, tenant: str, hold_id: str) -> bool:
    found = await meter.get_hold(tenant, hold_id)
    return found is not None and found.status == _COMMITTED


async def _install(
    factory: Any, tenant: str, image_id: uuid.UUID, named: str | None, hold_id: str, qty: int
) -> bool:
    async with factory() as db:
        got = await db.execute(
            update(Image)
            .where(
                Image.id == image_id,
                Image.tenant_id == tenant,
                Image.storage_hold_id.is_not_distinct_from(named),
            )
            .values(storage_hold_id=hold_id)
            .returning(Image.storage_bytes)
            .execution_options(include_deleted=True, synchronize_session=False)
        )
        row = got.first()
        if row is None:
            await db.rollback()
            return False
        if int(row[0]) != qty:
            await billing_ops.add_swap(db, image_id, int(row[0]), factory=factory)
        await finalize_session(db)
    return True
