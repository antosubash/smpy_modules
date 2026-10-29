"""``rehold``: replace an image's hold that lapsed before its commit.

A durable state machine on the claimed op row (``billing_settle``), so a
crash, a lapse or a second settler at any point resumes from the right step:

1. **Reserve** a replacement for the image's current total, keyed
   ``rehold-{op}-{generation}``, and persist ``replacement_hold_id`` on the op
   (conditional on the claim) *before* committing it. A crash between the
   reserve and the persist replays the same key and gets the same hold back.
2. **Commit** the replacement.
3. **Swap** it onto the image only while the image still names the lapsed
   hold (a conditional ``UPDATE``) *and* its ownership row moves
   ``reserved|orphan → installed`` (``sm_images.hold_refs``), and in the same
   transaction: on success a ``release`` of the lapsed hold, otherwise a
   ``release`` of the replacement (ours, referenced by nothing); and the op
   done, conditional on the claim. A replacement is only ever released
   through its ownership row, so a stale settler releasing it and a takeover
   installing it can never both win.

On resume with a replacement recorded, billing is asked for its state: held →
commit it; committed → swap; released, expired or unknown (``None``,
``HoldNotFound``: already released) → the key is spent,
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

from sm_images import billing, billing_ops, hold_refs
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
            state = await meter.get_hold(tenant, replacement)
            status = None if state is None else state.status
            if status == "held":
                try:
                    await meter.commit(replacement)
                    status = "committed"
                except HoldExpired:
                    status = "expired"
                except HoldNotFound:
                    status = None  # billing no longer knows it: already released
                await hook("rehold.committed", op)
            if status == "committed" and state is not None:
                if await _swap(factory, tenant, op, token, replacement, state.quantity):
                    return
                # a release won the replacement first: it is spent
            elif not await hold_refs.release(
                factory, tenant, replacement, meter, before=lambda: hook("rehold.releasing", op)
            ):
                raise ClaimLost(op.id)  # installed by the settler that took this op over
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
        await _persist(factory, tenant, op, token, replacement)
        await hook("rehold.persisted", op)
    raise RuntimeError(f"rehold of op {op.id} did not settle in {STEPS} steps")


async def _done(factory: Any, op: Op, token: str) -> None:
    await save(factory, op.id, token, done_at=datetime.now(UTC), last_error=None, claim_token=None)


async def _claimed(db: Any, op: Op, token: str, **values: Any) -> None:
    """Write ``values`` on our op in ``db``'s transaction; roll back and raise
    :class:`ClaimLost` when the claim is no longer ours."""
    got = await db.execute(
        update(BillingOp)
        .where(BillingOp.id == op.id, BillingOp.claim_token == token, BillingOp.done_at.is_(None))
        .values(**values)
        .returning(BillingOp.id)
        .execution_options(synchronize_session=False)
    )
    if got.first() is None:
        await db.rollback()
        raise ClaimLost(op.id)


async def _persist(factory: Any, tenant: str, op: Op, token: str, replacement: str) -> None:
    """Record the replacement on the op and its ``reserved`` ref, together."""
    async with factory() as db:
        await _claimed(db, op, token, replacement_hold_id=replacement)
        await hold_refs.reserved(db, tenant, replacement, op.image_id)
        await finalize_session(db)


async def _swap(
    factory: Any, tenant: str, op: Op, token: str, replacement: str, quantity: int
) -> bool:
    """Install ``replacement`` while the image still names the lapsed hold,
    queue the release of whichever hold is now unreferenced, and finish the op
    - one transaction, conditional on our claim. ``False`` (nothing written)
    when a release won the replacement first."""
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
        if moved.first() is not None:
            if not await hold_refs.install(db, tenant, replacement):
                await db.rollback()
                return False
            await hold_refs.orphan(db, tenant, op.hold_id)
            spare = op.hold_id
        else:  # the image moved on: the replacement is ours and unreferenced
            await hold_refs.orphan_reserved(db, tenant, replacement)
            spare = replacement
        await billing_ops.add(db, OP_RELEASE, image_id=op.image_id, hold_id=spare, factory=factory)
        await _claimed(db, op, token, done_at=datetime.now(UTC), last_error=None, claim_token=None)
        await finalize_session(db)
    return True
