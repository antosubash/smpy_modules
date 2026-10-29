"""Running a claimed storage-gauge op (:mod:`sm_images.billing_settle` claims it).

A ``swap`` (:func:`swap`): billing's swap from the hold the image
names now, then, in one transaction under the image's row lock, the new hold
written onto the image (only while it still names that old hold) and the op
done. When the image's ``storage_bytes`` is not what the op held (a
publication that grew the hold, then lost its fence) and no later swap is
queued, a correcting swap to ``storage_bytes`` is queued with it - a shrink,
which billing never refuses. An image that is gone, or names another hold,
gets nothing installed: the new hold's release is recorded (a ``release`` op)
under that same lock, in the transaction that finishes this op - the only op
that could have installed it. An ``ingest`` op reaching a settler means its
image was never inserted (that insert finishes the op itself, and cannot
while we hold the claim), so its release is recorded the same way. A
``release`` op is billing's ``release``, after the commit that decided it.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import select, update

from sm_images import billing, billing_ops
from sm_images.billing_settle import ClaimLost, Op
from sm_images.errors import StorageQuotaExceeded
from sm_images.models import BillingOp, Image
from sm_images.models.billing_op import NO_HOLD, OP_SWAP

__all__ = ["finish_op", "lock", "release_hold", "swap"]

logger = logging.getLogger(__name__)


async def swap(factory: Any, tenant: str, op: Op, mine: Any, meter: Any) -> None:
    present, named = False, None
    if op.op == OP_SWAP and op.image_id is not None:
        present, named = await _names(factory, tenant, op.image_id)
    fixed = op.old_hold_id
    if fixed is None:  # a queued swap: fix its old hold before billing hears of it
        fixed = named or NO_HOLD
        await _fix_old(factory, mine, fixed)
    old = None if fixed == NO_HOLD else fixed
    try:
        hold = await billing.swap(factory, tenant, old, op.quantity, mine.key, meter)
    except StorageQuotaExceeded as exc:  # nothing changed: the old hold still counts
        await finish_op(factory, mine, None, f"{type(exc).__name__}: {exc}")
        return
    if hold is None:
        await finish_op(factory, mine, None)
    elif not present:  # never inserted (fenced by our claim), or gone
        await _spare(factory, op, mine, hold.id)
    else:
        await _install(factory, tenant, op, mine, old, hold)


async def _fix_old(factory: Any, mine: Any, old: str) -> None:
    async with factory() as db:
        got = await db.execute(
            update(BillingOp)
            .where(
                BillingOp.id == mine.op_id,
                BillingOp.claim_token == mine.token,
                BillingOp.done_at.is_(None),
            )
            .values(old_hold_id=old)
            .returning(BillingOp.id)
            .execution_options(synchronize_session=False)
        )
        if got.first() is None:
            await db.rollback()
            raise ClaimLost(mine.op_id)
        await finalize_session(db)


async def _names(factory: Any, tenant: str, image_id: uuid.UUID) -> tuple[bool, str | None]:
    """Whether the image exists (trashed included), and the hold it names."""
    async with factory() as db:
        row = (
            await db.execute(
                select(Image.storage_hold_id)
                .where(Image.id == image_id, Image.tenant_id == tenant)
                .execution_options(include_deleted=True)
            )
        ).first()
        await finalize_session(db)
    return (False, None) if row is None else (True, row[0])


async def lock(db: Any, tenant: str, image_id: uuid.UUID) -> Any:
    """Take the image's row lock (trashed included: the same lock the executor's
    completion takes); ``(storage_hold_id, storage_bytes)``, or ``None`` when it
    is gone. Every decision to install or release an image's hold is taken
    under it."""
    return (
        await db.execute(
            update(Image)
            .where(Image.id == image_id, Image.tenant_id == tenant)
            .values(updated_at=Image.updated_at)
            .returning(Image.storage_hold_id, Image.storage_bytes)
            .execution_options(include_deleted=True, synchronize_session=False)
        )
    ).first()


async def _spare(factory: Any, op: Op, mine: Any, hold_id: str) -> None:
    """Our swap's hold will be named by no image: record its release and
    finish the op, one transaction (billing is called after the commit)."""
    async with factory() as db:
        await billing_ops.add_release(db, op.image_id, hold_id, factory=factory)
        if not await billing_ops.finish(db, mine, hold_id):
            await db.rollback()
            raise ClaimLost(op.id)
        await finalize_session(db)


async def _install(
    factory: Any, tenant: str, op: Op, mine: Any, old: str | None, hold: Any
) -> None:
    """Under the image's row lock: write ``hold`` onto the image while it still
    names ``old``; else (gone, or moved on) record ``hold``'s release - this op,
    finished in the same transaction, is the only one that could install it.
    :class:`ClaimLost` when the op is no longer ours."""
    assert op.image_id is not None
    async with factory() as db:
        row = await lock(db, tenant, op.image_id)
        if row is None or row[0] not in (old, hold.id):
            if row is not None:
                logger.warning("images.billing_op.moved op=%s image=%s", op.id, op.image_id)
            await billing_ops.add_release(db, op.image_id, hold.id, factory=factory)
        elif row[0] == old:
            await db.execute(
                update(Image)
                .where(Image.id == op.image_id, Image.tenant_id == tenant)
                .values(storage_hold_id=hold.id)
                .execution_options(include_deleted=True, synchronize_session=False)
            )
            later = [
                i for i in await billing_ops.pending_swaps(db, tenant, op.image_id) if i > op.id
            ]
            if int(row[1]) != op.quantity and not later:
                await billing_ops.add_swap(db, op.image_id, int(row[1]), factory=factory)
        if not await billing_ops.finish(db, mine, hold.id):
            await db.rollback()
            raise ClaimLost(op.id)
        await finalize_session(db)


async def release_hold(meter: Any, hold_id: str | None) -> None:
    from sm_billing.contracts.metering import HoldNotFound

    if hold_id is not None:
        with contextlib.suppress(HoldNotFound):  # already gone on billing's side
            await meter.release(hold_id)


async def finish_op(factory: Any, mine: Any, hold_id: str | None, error: str | None = None) -> None:
    async with factory() as db:
        if not await billing_ops.finish(db, mine, hold_id, error):
            await db.rollback()
            raise ClaimLost(mine.op_id)
        await finalize_session(db)
