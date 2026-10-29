"""The backstop: every image ends up counted by one committed hold of its
``storage_bytes`` (run by ``images.reconcile``, after the settler).

Every done ``swap`` or ``ingest`` op is examined once - whatever it ended
with: its hold, a refusal, an expiry or a closure. It is decided **correct**
only when the image's named hold is committed and of exactly the image's
``storage_bytes`` - as billing reports it now, read for every op: an op whose
own hold the image names, at the right size, is not taken on trust, since
that hold may have been released since (an admin's release) - and nothing
else of the op's still counts. Otherwise:

* the op's own hold still counts but the image does not name it (a lost
  swap) → installed where the image's named hold no longer counts, released
  where it does or the image is gone;
* the image is counted by nothing, or by a hold of the wrong size (a refusal,
  an expired shrink that left an oversized hold, a lost correction) → a swap
  to ``storage_bytes`` from what it names is queued. If that swap is refused
  too, its op is itself a candidate of the next lap, so the image is tried
  again until it is counted right.

**An op whose outcome is unknown gets one from billing first.** An op
expired without a hold recorded asks ``close_key`` for its key: the hold a
swap made under it (recorded on the op before anything else), its refusal or
expiry, or ``Closed`` - and from then no call under the key can write. If
billing cannot answer, the op is left unexamined and tried on the next lap.

**Serialised per image (race R).** Billing is read first (never under a
lock: SQLite), then the decision is taken under the image's row lock
(``billing_install.lock``), re-reading what the image names and stores and
its unfinished ops: an image with any op still unfinished is left to that
op, and one that moved since the reads is looked at again next lap. A
release is only recorded there - a ``release`` op in that transaction, run
after the commit - so no other decision can install the hold meanwhile.

The scan walks bounded laps (``billing_repair_cursor``). A decided op is
stamped ``repaired_at``; the sweep keeps an unexamined one.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import and_, select, update

from sm_images import billing, billing_ops
from sm_images import billing_repair_cursor as cursor
from sm_images.billing_install import lock
from sm_images.billing_settle import OP_EXPIRED
from sm_images.models import BillingOp, Image
from sm_images.models.billing_op import OP_INGEST, OP_SWAP

__all__ = ["CAP", "candidate", "repair"]

logger = logging.getLogger(__name__)
CAP = 200
_COMMITTED = "committed"
_COLUMNS = (
    BillingOp.id,
    BillingOp.image_id,
    BillingOp.hold_id,
    BillingOp.quantity,
    BillingOp.idempotency_key,
    BillingOp.last_error,
    Image.id,
    Image.storage_hold_id,
    Image.storage_bytes,
)


def candidate() -> Any:
    """A done op the repair has yet to examine. Never SQL ``NULL``, so
    ``~candidate()`` - the sweep's - is exactly its complement."""
    return and_(
        BillingOp.op.in_((OP_SWAP, OP_INGEST)),
        BillingOp.image_id.is_not(None),
        BillingOp.repaired_at.is_(None),
    )


async def repair(factory: Any, tenant: str, now: datetime | None = None) -> int:
    """Examine the next :data:`CAP` candidates of the tenant's lap; how many
    images were repaired."""
    meter = billing.storage_meter(factory)
    if meter is None:
        return 0
    lap = await cursor.begin(factory, tenant)
    if lap is None or lap.end is None:
        return 0
    now = now or datetime.now(UTC)
    async with factory() as db:
        stmt = (
            select(*_COLUMNS)
            .outerjoin(Image, and_(Image.id == BillingOp.image_id, Image.tenant_id == tenant))
            .where(
                BillingOp.tenant_id == tenant,
                BillingOp.done_at.is_not(None),
                BillingOp.id > lap.last,
                BillingOp.id <= lap.end,
                candidate(),
            )
            .order_by(BillingOp.id)
            .limit(CAP)
            .execution_options(include_deleted=True)
        )
        rows = (await db.execute(stmt)).all()
        await db.rollback()
    fixed = 0
    for row in rows:
        try:
            fixed += await _examine(factory, tenant, meter, row, now) or 0
        except Exception:  # billing unreachable: left unexamined, tried next lap
            logger.warning("images.billing_repair.failed op=%s", row[0], exc_info=True)
    full = len(rows) == CAP
    await cursor.move(factory, tenant, lap, rows[-1][0] if full else 0, lap.end if full else None)
    return fixed


async def _examine(factory: Any, tenant: str, meter: Any, row: Any, now: datetime) -> int | None:
    op_id, image_id, hold_id, _qty, key, error, present, named, stored = row
    if hold_id is None and error == OP_EXPIRED and key:  # outcome unknown: get a final one
        hold_id = billing.held_by(await billing.close_key(factory, tenant, key, meter))
        if hold_id is not None:
            await _record_hold(factory, op_id, hold_id)
    orphan = None
    if hold_id is not None and hold_id != named:
        found = await meter.get_hold(tenant, hold_id)
        orphan = found if found is not None and found.status == _COMMITTED else None
    current = None if named is None else await meter.get_hold(tenant, named)
    counted = current is not None and current.status == _COMMITTED
    right = present is None or (counted and current.quantity == int(stored)) or int(stored) < 1
    if orphan is None and right:
        await _decided(factory, op_id, now)  # nothing lost, counted right
        return 0
    seen = None if present is None else (named, int(stored))
    return await _decide(factory, tenant, op_id, image_id, seen, orphan, counted, right, now)


async def _record_hold(factory: Any, op_id: int, hold_id: str) -> None:
    async with factory() as db:
        await db.execute(
            update(BillingOp)
            .where(BillingOp.id == op_id, BillingOp.hold_id.is_(None))
            .values(hold_id=hold_id)
            .execution_options(synchronize_session=False)
        )
        await finalize_session(db)


async def _decide(
    factory: Any,
    tenant: str,
    op_id: int,
    image_id: uuid.UUID,
    seen: tuple[str | None, int] | None,
    orphan: Any,
    counted: bool,
    right: bool,
    now: datetime,
) -> int | None:
    """Act under the image's row lock; 1 if something was repaired, ``None``
    when the image moved since the reads (``seen``: what it named and stored,
    ``None`` if gone), or has an op unfinished (left for the next lap)."""
    async with factory() as db:
        row = await lock(db, tenant, image_id)
        now_seen = None if row is None else (row[0], int(row[1]))
        if await billing_ops.unfinished(db, tenant, image_id) or now_seen != seen:
            await db.rollback()
            return None
        if orphan is not None and (row is None or counted):
            await billing_ops.add_release(db, image_id, orphan.id, factory=factory)
        elif orphan is not None:
            await db.execute(
                update(Image)
                .where(Image.id == image_id, Image.tenant_id == tenant)
                .values(storage_hold_id=orphan.id)
                .execution_options(include_deleted=True, synchronize_session=False)
            )
            right = orphan.quantity == int(row[1])
            counted = True
        if row is not None and not right and (counted or orphan is None):
            await billing_ops.add_swap(db, image_id, int(row[1]), factory=factory)
        await _stamp(db, op_id, now)
        await finalize_session(db)
    logger.warning("images.billing_repair image=%s op=%s", image_id, op_id)
    return 1


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
