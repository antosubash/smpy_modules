"""The backstop for a swap the image never took (run by ``images.reconcile``).

A done ``swap`` or ``ingest`` op records the hold billing gave it. Normally the
image names that hold (the op installed it) or billing released it (a later
swap replaced it, the image is gone, the op released it). If neither - billing
reports the op's hold **committed** while the image names another - the image
lost a committed swap. And an op finished ``op_expired`` (too old to call
billing, ``billing_settle.BILLING_OP_MAX_AGE``) may have left its image
counted by nothing. :func:`repair` reconciles both:

* the image names a hold that no longer counts → the op's committed hold is
  written onto it (a correcting swap queued if its size differs), or - an
  expired op, with no hold of its own - a swap from what it names is queued;
* the image is counted already, or is gone → the op's committed hold is
  released.

**Serialised per image (race R).** Billing is read first (never under a
lock: SQLite), then the decision is taken under the image's row lock
(``billing_install.lock``), re-reading the hold it names and its unfinished
ops: an image with any op still unfinished is left to that op, and one whose
hold moved since the reads is looked at again next pass. A release is only
recorded there - a ``release`` op in that transaction, run after the commit -
so no other decision can install the hold meanwhile (it would see that op).

**Every candidate is examined, oldest first**, and stamped ``repaired_at``
once decided; the sweep keeps an unexamined one. :data:`CAP` per call. A
healthy op (its image names its hold) costs no billing read.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import and_, or_, select, update

from sm_images import billing, billing_ops
from sm_images.billing_install import lock
from sm_images.billing_settle import OP_EXPIRED
from sm_images.models import BillingOp, Image
from sm_images.models.billing_op import OP_INGEST, OP_SWAP

__all__ = ["CAP", "candidate", "repair"]

logger = logging.getLogger(__name__)
CAP = 200
_COMMITTED = "committed"


def candidate() -> Any:
    """A done op the repair has yet to examine."""
    return and_(
        BillingOp.op.in_((OP_SWAP, OP_INGEST)),
        BillingOp.image_id.is_not(None),
        BillingOp.repaired_at.is_(None),
        or_(BillingOp.hold_id.is_not(None), BillingOp.last_error == OP_EXPIRED),
    )


async def repair(factory: Any, tenant: str, now: datetime | None = None) -> int:
    """Examine the tenant's oldest :data:`CAP` candidates; how many were repaired."""
    meter = billing.storage_meter(factory)
    if meter is None:
        return 0
    now = now or datetime.now(UTC)
    stmt = (
        select(BillingOp.id, BillingOp.image_id, BillingOp.hold_id, Image.storage_hold_id)
        .outerjoin(Image, and_(Image.id == BillingOp.image_id, Image.tenant_id == tenant))
        .where(BillingOp.tenant_id == tenant, BillingOp.done_at.is_not(None), candidate())
        .order_by(BillingOp.id)
        .limit(CAP)
        .execution_options(include_deleted=True)
    )
    async with factory() as db:
        rows = (await db.execute(stmt)).all()
        await finalize_session(db)
    fixed = 0
    for op_id, image_id, hold_id, named in rows:
        if hold_id is not None and named == hold_id:
            await _decided(factory, op_id, now)  # healthy: no billing read
            continue
        orphan = None if hold_id is None else await meter.get_hold(tenant, hold_id)
        if hold_id is not None and (orphan is None or orphan.status != _COMMITTED):
            await _decided(factory, op_id, now)  # released or replaced: nothing lost
            continue
        counted = named is not None and await _committed(meter, tenant, named)
        got = await _decide(factory, tenant, op_id, image_id, named, orphan, counted, now)
        fixed += got or 0
    return fixed


async def _committed(meter: Any, tenant: str, hold_id: str) -> bool:
    found = await meter.get_hold(tenant, hold_id)
    return found is not None and found.status == _COMMITTED


async def _decide(
    factory: Any,
    tenant: str,
    op_id: int,
    image_id: uuid.UUID,
    named: str | None,
    orphan: Any,
    counted: bool,
    now: datetime,
) -> int | None:
    """Act under the image's row lock; 1 if something was repaired, 0 if not,
    ``None`` when the image moved since the reads (left for the next pass)."""
    async with factory() as db:
        row = await lock(db, tenant, image_id)
        if await billing_ops.unfinished(db, tenant, image_id) or (
            row is not None and row[0] != named
        ):
            await db.rollback()
            return None
        acted = 1
        if orphan is not None and (row is None or counted):
            await billing_ops.add_release(db, image_id, orphan.id, factory=factory)
        elif orphan is not None:
            await db.execute(
                update(Image)
                .where(Image.id == image_id, Image.tenant_id == tenant)
                .values(storage_hold_id=orphan.id)
                .execution_options(include_deleted=True, synchronize_session=False)
            )
            if int(row[1]) != orphan.quantity:
                await billing_ops.add_swap(db, image_id, int(row[1]), factory=factory)
        elif row is not None and not counted:  # an expired op: the image counts nothing
            await billing_ops.add_swap(db, image_id, int(row[1]), factory=factory)
        else:
            acted = 0
        await _stamp(db, op_id, now)
        await finalize_session(db)
    if acted:
        logger.warning("images.billing_repair image=%s op=%s", image_id, op_id)
    return acted


async def _stamp(db: Any, op_id: int, now: datetime) -> None:
    await db.execute(
        update(BillingOp)
        .where(BillingOp.id == op_id)
        .values(repaired_at=now)
        .execution_options(synchronize_session=False)
    )


async def _decided(factory: Any, op_id: int, now: datetime) -> None:
    async with factory() as db:
        await _stamp(db, op_id, now)
        await finalize_session(db)
