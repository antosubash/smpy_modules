"""The storage gauge's durable settlement outbox (``images_billing_op``).

Every settlement of a hold - ``commit`` the new one, ``release`` the old one -
is a row written **in the same transaction** as the state change it settles:
ingest's insert, the executor's fenced completion, the janitor's purge. So a
crash, a rollback or a billing outage never loses one, and nothing releases a
hold in a path that could only log a failure.

* After the commit a best-effort attempt runs the transaction's own ops.
* Whatever fails stays pending with a backoff; ``images.reconcile`` retries
  each tenant's due ops in bounded pages until billing confirms. Every op is
  **claimed** before it runs, so two settlers never run one twice
  (:mod:`sm_images.billing_settle`).
* **Order.** An image's ``release`` of its old hold names the ``commit`` of its
  new one in ``after_id``, and runs only once that is done *and* billing
  confirms the hold the image names now is committed.
* **A new hold that lapsed** before its commit turns the op into a ``rehold``
  (:mod:`sm_images.billing_rehold`).
* The janitor deletes done ops after the grace period (:func:`sweep`).

Ops are tenant rows (``MultiTenantMixin``); every query here also names the
tenant, which the caller has bound.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import delete, exists, select
from sqlalchemy.orm import aliased

from sm_images import billing
from sm_images.models import BillingOp
from sm_images.models.billing_op import OP_COMMIT, OP_RELEASE

__all__ = ["add", "add_swap", "release_now", "release_storage", "settle", "sweep"]

logger = logging.getLogger(__name__)
SWEEP_BATCH = 500
SWEEP_BATCHES = 20

StorageHold = tuple[uuid.UUID, str | None, int]
"""``(image_id, storage_hold_id, storage_bytes)`` of a hard-deleted image."""


# -- writing ops (in the caller's transaction) --------------------------------


async def add(
    db: Any,
    op: str,
    *,
    image_id: uuid.UUID | None,
    hold_id: str,
    quantity: int = 0,
    after: BillingOp | None = None,
    factory: Any = None,
) -> BillingOp:
    """Write one op and queue its attempt for after ``db`` commits."""
    row = BillingOp(
        op=op,
        image_id=image_id,
        hold_id=hold_id,
        quantity=quantity,
        after_id=None if after is None else after.id,
    )
    db.add(row)
    await db.flush()
    tenant = row.tenant_id
    billing.on_commit(db, settle, billing.factory_of(db, factory), tenant, [row.id])
    return row


async def add_swap(
    db: Any, image_id: uuid.UUID, new: str, quantity: int, old: str | None, *, factory: Any = None
) -> None:
    """``commit`` the image's new hold, then ``release`` its old one."""
    first = await add(
        db, OP_COMMIT, image_id=image_id, hold_id=new, quantity=quantity, factory=factory
    )
    if old is not None and old != new:
        await add(db, OP_RELEASE, image_id=image_id, hold_id=old, after=first, factory=factory)


async def release_storage(db: Any, holds: list[StorageHold], factory: Any = None) -> None:
    """The janitor's purge: the hard-deleted images' holds, released once its
    transaction commits (the op keeps the hold id; the row is gone)."""
    from sm_images import hold_refs
    from sm_images.tenancy import bound_tenant

    for image_id, hold, size in holds:
        if hold:
            await hold_refs.orphan(db, bound_tenant(), hold)
            await add(
                db, OP_RELEASE, image_id=image_id, hold_id=hold, quantity=size, factory=factory
            )


async def release_now(factory: Any, image_id: uuid.UUID | None, hold: str | None) -> None:
    """Outside any transaction (the caller rolled back): a ``release`` op in a
    short transaction of its own, then its attempt."""
    if hold is None:
        return
    async with factory() as db:
        await add(db, OP_RELEASE, image_id=image_id, hold_id=hold, factory=factory)
        await finalize_session(db)


# -- settling and sweeping ---------------------------------------------------


async def settle(
    factory: Any, tenant: str, ids: list[int] | None = None, now: datetime | None = None
) -> int:
    """Claim and run the due ops (:func:`sm_images.billing_settle.settle`)."""
    from sm_images import billing_settle

    return await billing_settle.settle(factory, tenant, ids, now)


async def sweep(factory: Any, tenant: str, cutoff: datetime) -> int:
    """Delete ops done before ``cutoff``, :data:`SWEEP_BATCH` per transaction and
    at most :data:`SWEEP_BATCHES` transactions per call - never one a pending op
    still waits for (``after_id``)."""
    waiting = aliased(BillingOp)
    needed = exists().where(waiting.after_id == BillingOp.id, waiting.done_at.is_(None))
    removed = 0
    for _ in range(SWEEP_BATCHES):
        async with factory() as db:
            ids = select(BillingOp.id).where(
                BillingOp.tenant_id == tenant,
                BillingOp.done_at.is_not(None),
                BillingOp.done_at < cutoff,
                ~needed,
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
