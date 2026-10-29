"""``rehold``: replace an image's hold that lapsed before its commit.

A durable state machine on the claimed op row (``billing_settle``), so a
crash, a lapse or a second settler at any point resumes from the right step:

1. **Reserve** a replacement for the image's current total, keyed
   ``rehold-{op}-{generation}``, and persist ``replacement_hold_id`` on the op
   (conditional on the claim) *before* committing it. A crash between the
   reserve and the persist replays the same key and gets the same hold back.
2. **Commit** the replacement.
3. **Swap** it onto the image only while the image still names the lapsed
   hold (a conditional ``UPDATE``), and in the same transaction: on success a
   ``release`` of the lapsed hold, otherwise a ``release`` of the replacement
   (ours, referenced by nothing); and the op done, conditional on the claim.

On resume with a replacement recorded, billing is asked for its state: held →
commit it; committed → swap; released, expired or unknown → the key is spent,
so it is released (a lapsed hold counts until billing's sweeper settles it),
``generation`` moves on and a new replacement is reserved under a new key.
A key is never reused. An image that is gone, or names another hold already,
needs nothing installed: the op is done (and ``billing_settle`` makes the old
hold's release wait until the hold the image names is committed).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import update

from sm_images import billing, billing_ops
from sm_images.billing_settle import ClaimLost, Op, hook, save
from sm_images.models import BillingOp, Image
from sm_images.models.billing_op import OP_RELEASE

__all__ = ["run"]

STEPS = 4
"""Replacements one claim may try before it gives up and backs off."""


def key(op: Op, generation: int) -> str:
    assert op.image_id is not None
    return billing.hold_key(op.image_id, f"rehold-{op.id}-{generation}")


async def _current(factory: Any, tenant: str, op: Op) -> tuple[str | None, int] | None:
    """``(hold the image names, its total)``; ``None`` when the image is gone."""
    from sm_images.pipeline.storage_hold import parts

    assert op.image_id is not None
    async with factory() as db:
        found = await parts(db, tenant, op.image_id, include_deleted=True)
        await finalize_session(db)
    return None if found is None else (found[3], found[0] + found[1] + found[2])


async def run(factory: Any, tenant: str, op: Op, token: str, meter: Any) -> None:
    from sm_billing.contracts.metering import HoldExpired, HoldNotFound

    replacement, generation = op.replacement_hold_id, op.generation
    for _ in range(STEPS):
        if replacement is not None:
            state = await meter.get_hold(replacement)
            status = None if state is None else state.status
            if status == "held":
                try:
                    await meter.commit(replacement)
                    status = "committed"
                except (HoldExpired, HoldNotFound):
                    status = "expired"
                await hook("rehold.committed", op)
            if status == "committed" and state is not None:
                await _swap(factory, tenant, op, token, replacement, state.quantity)
                return
            await meter.release(replacement)  # a lapsed hold may still count until swept
            generation, replacement = generation + 1, None  # spent: never reuse its key
            await save(factory, op.id, token, replacement_hold_id=None, generation=generation)
            continue
        current = await _current(factory, tenant, op)
        if current is None or current[0] != op.hold_id:
            await _done(factory, op, token)  # gone, or moved on: nothing to install
            return
        try:
            hold = await billing.reserve(factory, tenant, current[1], key(op, generation))
        except billing.HoldSpent:
            generation += 1
            await save(factory, op.id, token, generation=generation)
            continue
        await hook("rehold.reserved", op)
        if hold is None:
            await _done(factory, op, token)
            return
        replacement = hold.id
        await save(factory, op.id, token, replacement_hold_id=replacement)
        await hook("rehold.persisted", op)
    raise RuntimeError(f"rehold of op {op.id} did not settle in {STEPS} steps")


async def _done(factory: Any, op: Op, token: str) -> None:
    await save(factory, op.id, token, done_at=datetime.now(UTC), last_error=None, claim_token=None)


async def _swap(
    factory: Any, tenant: str, op: Op, token: str, replacement: str, quantity: int
) -> None:
    """Install ``replacement`` while the image still names the lapsed hold,
    queue the release of whichever hold is now unreferenced, and finish the op
    - one transaction, conditional on our claim."""
    async with factory() as db:
        moved = await db.execute(
            update(Image)
            .where(
                Image.id == op.image_id,
                Image.tenant_id == tenant,
                Image.storage_hold_id == op.hold_id,
            )
            .values(storage_hold_id=replacement, storage_bytes=quantity)
            .returning(Image.id)
            .execution_options(include_deleted=True, synchronize_session=False)
        )
        spare = op.hold_id if moved.first() is not None else replacement
        await billing_ops.add(db, OP_RELEASE, image_id=op.image_id, hold_id=spare, factory=factory)
        finished = await db.execute(
            update(BillingOp)
            .where(
                BillingOp.id == op.id,
                BillingOp.claim_token == token,
                BillingOp.done_at.is_(None),
            )
            .values(done_at=datetime.now(UTC), last_error=None, claim_token=None)
            .returning(BillingOp.id)
            .execution_options(synchronize_session=False)
        )
        if finished.first() is None:
            await db.rollback()
            raise ClaimLost(op.id)
        await finalize_session(db)
