"""The storage gauge's durable settlement outbox (``images_billing_op``).

Every settlement of a hold - ``commit`` the new one, ``release`` the old one -
is a row written **in the same transaction** as the state change it settles:
ingest's insert, the executor's fenced completion, the janitor's purge. So a
crash, a rollback or a billing outage never loses one, and nothing releases a
hold in a path that could only log a failure.

* After the commit a best-effort attempt runs the transaction's own ops.
* Whatever fails stays pending with a backoff (``attempts``,
  ``next_attempt_at``, ``last_error``); ``images.reconcile`` retries each
  tenant's due ops in bounded pages until billing confirms. Every op is
  idempotent on billing's side, so a duplicate attempt is harmless.
* **Order.** An image's ``release`` of its old hold names the ``commit`` of its
  new one in ``after_id`` and runs only once that is done: the image is never
  left holding nothing while billing is down.
* **A new hold that lapsed** before its commit (``HoldExpired``) turns the op
  into a ``rehold``: a fresh committed hold for the image's current total
  (recomputed from its rows), swapped onto the image only while it still names
  the lapsed one. Then the waiting ``release`` of the old hold runs.

Ops are tenant rows (``MultiTenantMixin``); every query here also names the
tenant, which the caller has bound.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import aliased

from sm_images import billing
from sm_images.models import BillingOp, Image
from sm_images.models.billing_op import OP_COMMIT, OP_REHOLD, OP_RELEASE

__all__ = ["add", "add_swap", "release_now", "release_storage", "settle"]

logger = logging.getLogger(__name__)
PAGE = 100
PAGES = 10
BACKOFF = timedelta(minutes=1)
BACKOFF_MAX = timedelta(hours=1)

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
    for image_id, hold, size in holds:
        if hold:
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


# -- settling -----------------------------------------------------------------


_COLUMNS = (BillingOp.id, BillingOp.op, BillingOp.image_id, BillingOp.hold_id, BillingOp.attempts)


def _due(tenant: str, now: datetime, ids: list[int] | None) -> Any:
    prior = aliased(BillingOp)
    waited = exists().where(prior.id == BillingOp.after_id, prior.done_at.is_not(None))
    stmt = select(*_COLUMNS).where(
        BillingOp.tenant_id == tenant,
        BillingOp.done_at.is_(None),
        or_(BillingOp.next_attempt_at.is_(None), BillingOp.next_attempt_at <= now),
        or_(BillingOp.after_id.is_(None), waited),
    )
    if ids is not None:
        stmt = stmt.where(BillingOp.id.in_(ids))
    return stmt.order_by(BillingOp.id).limit(PAGE)


async def settle(
    factory: Any, tenant: str, ids: list[int] | None = None, now: datetime | None = None
) -> int:
    """Run the due ops (``ids`` only, when given), dependants after what they
    wait for; how many were confirmed. Bounded to :data:`PAGES` pages."""
    now = now or datetime.now(UTC)
    done = 0
    for _ in range(PAGES):
        async with factory() as db:
            rows = list((await db.execute(_due(tenant, now, ids))).all())
            await finalize_session(db)
        ran = [await _run(factory, tenant, row, now) for row in rows]
        done += sum(ran)
        if not any(ran):
            break
    return done


async def _run(factory: Any, tenant: str, row: Any, now: datetime) -> bool:
    meter = billing.storage_meter(factory)
    try:
        if meter is not None:
            await _apply(factory, tenant, row, meter)
    except Exception as exc:
        logger.warning("images.billing_op.failed op=%s id=%s", row.op, row.id, exc_info=True)
        await _failed(factory, row, now, exc)
        return False
    await _finish(factory, row.id, now)
    return True


async def _apply(factory: Any, tenant: str, row: Any, meter: Any) -> None:
    from sm_billing.contracts.metering import HoldExpired, HoldNotFound

    if row.op == OP_RELEASE:
        await meter.release(row.hold_id)
        return
    if row.op == OP_COMMIT:
        try:
            await meter.commit(row.hold_id)
            return
        except (HoldExpired, HoldNotFound):
            await _become_rehold(factory, row)
    await _rehold(factory, tenant, row, meter)


async def _become_rehold(factory: Any, row: Any) -> None:
    async with factory() as db:
        await db.execute(
            update(BillingOp)
            .where(BillingOp.id == row.id, BillingOp.done_at.is_(None))
            .values(op=OP_REHOLD)
            .execution_options(synchronize_session=False)
        )
        await finalize_session(db)


async def _rehold(factory: Any, tenant: str, row: Any, meter: Any) -> None:
    """A fresh committed hold for the image's current total, swapped onto the
    image only while it still names the lapsed hold ``row.hold_id``."""
    from sm_images.pipeline.storage_hold import parts

    assert row.image_id is not None
    async with factory() as db:
        found = await parts(db, tenant, row.image_id, include_deleted=True)
        await finalize_session(db)
    if found is None or found[3] != row.hold_id:
        return  # purged, or the image moved on: its newer hold's own ops count it
    total = found[0] + found[1] + found[2]
    key = billing.hold_key(row.image_id, f"rehold-{row.id}")
    hold = await billing.reserve(factory, tenant, total, key)
    if hold is None:
        return
    await meter.commit(hold.id)
    async with factory() as db:
        moved = await db.execute(
            update(Image)
            .where(
                Image.id == row.image_id,
                Image.tenant_id == tenant,
                Image.storage_hold_id == row.hold_id,
            )
            .values(storage_hold_id=hold.id, storage_bytes=total)
            .returning(Image.id)
            .execution_options(include_deleted=True, synchronize_session=False)
        )
        if moved.first() is None:  # lost to a newer hold: give the fresh one back
            await add(db, OP_RELEASE, image_id=row.image_id, hold_id=hold.id, factory=factory)
        await finalize_session(db)


async def _finish(factory: Any, op_id: int | None, now: datetime) -> None:
    async with factory() as db:
        await db.execute(
            update(BillingOp)
            .where(BillingOp.id == op_id, BillingOp.done_at.is_(None))
            .values(done_at=now, last_error=None)
            .execution_options(synchronize_session=False)
        )
        await finalize_session(db)


async def _failed(factory: Any, row: Any, now: datetime, exc: Exception) -> None:
    attempts = row.attempts + 1
    wait = min(BACKOFF * 2 ** min(attempts - 1, 10), BACKOFF_MAX)
    async with factory() as db:
        await db.execute(
            update(BillingOp)
            .where(BillingOp.id == row.id, BillingOp.done_at.is_(None))
            .values(
                attempts=attempts,
                next_attempt_at=now + wait,
                last_error=f"{type(exc).__name__}: {exc}"[:500],
            )
            .execution_options(synchronize_session=False)
        )
        await finalize_session(db)
