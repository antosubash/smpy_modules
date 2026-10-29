"""The storage gauge's durable outbox (``images_billing_op``): writing ops.

Billing writes in its own transaction, so a change of what an image stores
and the billing call that settles it cannot commit together. Every billing
call images makes is therefore driven by an op row, written first:

* ``ingest`` - a new image's first hold, ``swap`` from no hold. Written and
  claimed before the billing call (:func:`open_op`); the image insert marks it
  done in its own transaction (:func:`finish`). An insert that does not
  happen hands it back (:func:`hand_back`), and the settler releases its hold.
* ``swap`` - move an image's hold to a new quantity. A publication that grows
  the image writes it claimed and calls billing *before* publishing (a refusal
  publishes nothing); one that shrinks it (or a correction) writes it in its
  own transaction, settled after the commit (:func:`add_swap`) - a shrink
  always fits.
* ``release`` - a purged image's hold (:func:`release_storage`).

Settling - claims, the per-image order, installing the new hold on the image -
is :mod:`sm_images.billing_settle`; reconcile retries what is left, and the
janitor deletes done ops after the grace period (:func:`sweep`). Ops are
tenant rows (``MultiTenantMixin``); every query also names the tenant.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import delete, select, update

from sm_images import billing
from sm_images.models import BillingOp
from sm_images.models.billing_op import NO_HOLD, OP_RELEASE, OP_SWAP

__all__ = [
    "Claimed",
    "add_release",
    "add_swap",
    "finish",
    "hand_back",
    "open_op",
    "pending_swaps",
    "release_storage",
    "settle",
    "sweep",
    "unfinished",
]

SWEEP_BATCH = 500
SWEEP_BATCHES = 20

StorageHold = tuple[uuid.UUID, str | None, int]
"""``(image_id, storage_hold_id, storage_bytes)`` of a hard-deleted image."""


@dataclass(frozen=True)
class Claimed:
    """An op its writer claimed: only ``token`` may finish it."""

    op_id: int
    token: str
    key: str


async def open_op(
    db: Any,
    op: str,
    image_id: uuid.UUID,
    qty: int,
    key: str,
    *,
    claim: timedelta,
    old: str | None,
) -> Claimed:
    """Write an op claimed by the caller for ``claim``, in ``db``'s transaction,
    replacing ``old`` (``None``: no hold)."""
    token = uuid.uuid4().hex
    row = BillingOp(
        op=op,
        image_id=image_id,
        quantity=qty,
        idempotency_key=key,
        old_hold_id=old or NO_HOLD,
        claim_token=token,
        claim_expires_at=datetime.now(UTC) + claim,
    )
    db.add(row)
    await db.flush()
    assert row.id is not None
    return Claimed(row.id, token, key)


def _mine(claimed: Claimed) -> list[Any]:
    return [
        BillingOp.id == claimed.op_id,
        BillingOp.claim_token == claimed.token,
        BillingOp.done_at.is_(None),
    ]


async def finish(db: Any, claimed: Claimed, hold_id: str | None, error: str | None = None) -> bool:
    """Mark our op done, in ``db``'s transaction; ``False`` when it is no
    longer ours (a settler took it over: the caller must not commit)."""
    got = await db.execute(
        update(BillingOp)
        .where(*_mine(claimed))
        .values(done_at=datetime.now(UTC), hold_id=hold_id, last_error=error, claim_token=None)
        .returning(BillingOp.id)
        .execution_options(synchronize_session=False)
    )
    return got.first() is not None


async def hand_back(db: Any, claimed: Claimed | None, factory: Any = None) -> None:
    """Give our op to the settler (after ``db`` commits): whatever billing did
    under its key is settled from there."""
    if claimed is None:
        return
    await db.execute(
        update(BillingOp)
        .where(*_mine(claimed))
        .values(claim_token=None, claim_expires_at=None)
        .execution_options(synchronize_session=False)
    )
    _settle_after(db, [claimed.op_id], factory)


async def add_swap(db: Any, image_id: uuid.UUID, qty: int, *, factory: Any = None) -> BillingOp:
    """Move the image's hold to ``qty`` once ``db`` commits (a shrink or a
    correction: never refused). Runs after the image's earlier swaps."""
    row = BillingOp(
        op=OP_SWAP,
        image_id=image_id,
        quantity=qty,
        idempotency_key=billing.hold_key(image_id, f"swap-{uuid.uuid4().hex}"),
    )
    db.add(row)
    await db.flush()
    assert row.id is not None
    _settle_after(db, [row.id], factory)
    return row


async def release_storage(db: Any, holds: list[StorageHold], factory: Any = None) -> None:
    """The janitor's purge: the hard-deleted images' holds, released once its
    transaction commits (the op keeps the hold id; the row is gone)."""
    ids = []
    for image_id, hold, size in holds:
        if hold:
            row = BillingOp(op=OP_RELEASE, image_id=image_id, hold_id=hold, quantity=size)
            db.add(row)
            await db.flush()
            ids.append(row.id)
    if ids:
        _settle_after(db, ids, factory)


async def add_release(
    db: Any, image_id: uuid.UUID | None, hold_id: str, *, factory: Any = None
) -> None:
    """Release ``hold_id`` once ``db`` commits: the intent, recorded where the
    decision was taken (under the image's row lock)."""
    row = BillingOp(op=OP_RELEASE, image_id=image_id, hold_id=hold_id)
    db.add(row)
    await db.flush()
    _settle_after(db, [row.id], factory)


async def unfinished(db: Any, tenant: str, image_id: uuid.UUID) -> list[int]:
    """Every op of the image not done yet (any kind)."""
    stmt = select(BillingOp.id).where(
        BillingOp.tenant_id == tenant,
        BillingOp.image_id == image_id,
        BillingOp.done_at.is_(None),
    )
    return list((await db.execute(stmt)).scalars())


async def pending_swaps(db: Any, tenant: str, image_id: uuid.UUID) -> list[int]:
    """The image's ``swap`` ops not done yet, oldest first."""
    stmt = (
        select(BillingOp.id)
        .where(
            BillingOp.tenant_id == tenant,
            BillingOp.image_id == image_id,
            BillingOp.op == OP_SWAP,
            BillingOp.done_at.is_(None),
        )
        .order_by(BillingOp.id)
    )
    return list((await db.execute(stmt)).scalars())


def _settle_after(db: Any, ids: list[int], factory: Any) -> None:
    from sm_images.tenancy import bound_tenant

    billing.on_commit(db, settle, billing.factory_of(db, factory), bound_tenant(), ids)


async def settle(
    factory: Any, tenant: str, ids: list[int] | None = None, now: datetime | None = None
) -> int:
    """Claim and run the due ops (:func:`sm_images.billing_settle.settle`)."""
    from sm_images import billing_settle

    return await billing_settle.settle(factory, tenant, ids, now)


async def sweep(factory: Any, tenant: str, cutoff: datetime) -> int:
    """Delete ops done before ``cutoff``, :data:`SWEEP_BATCH` per transaction and
    at most :data:`SWEEP_BATCHES` transactions per call - never one the repair
    has yet to examine (``sm_images.billing_repair``)."""
    from sm_images.billing_repair import candidate

    removed = 0
    for _ in range(SWEEP_BATCHES):
        async with factory() as db:
            ids = select(BillingOp.id).where(
                BillingOp.tenant_id == tenant,
                BillingOp.done_at.is_not(None),
                BillingOp.done_at < cutoff,
                ~candidate(),
            )
            batch = list(
                (await db.execute(ids.order_by(BillingOp.id).limit(SWEEP_BATCH))).scalars()
            )
            if batch:
                await db.execute(
                    delete(BillingOp)
                    .where(BillingOp.tenant_id == tenant, BillingOp.id.in_(batch))
                    .execution_options(synchronize_session=False)
                )
            await finalize_session(db)
        removed += len(batch)
        if len(batch) < SWEEP_BATCH:
            break
    return removed
