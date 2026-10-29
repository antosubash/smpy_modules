"""What ingest hands around: a reserved :class:`Slot` (intent and storage hold
taken before the caller's transaction writes), a :class:`Duplicate` answer,
and the file name a row keeps.

The storage hold (``sm_images.billing``): an ``ingest`` op is written and
claimed in a short transaction of its own, then billing swaps from no hold -
a committed hold for the original, or a refusal - under a key of this
attempt's own (two ``complete`` calls for one image never share one). The
image insert marks the op done in its savepoint (:func:`keep_hold`); a
duplicate or a failed insert hands the op back (:func:`drop_hold`) and the
settler releases the hold. Every outcome billing gives the key (a hold, a
refusal, an expiry or a closure) is final. A writer that dies keeps its claim for
:data:`INGEST_CLAIM`; a settler then takes the op over and releases the hold -
and an insert still running after that cannot finish the op, so it fails
rather than naming a released hold.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from simple_module_db import finalize_session, mark_written

from sm_images import billing, billing_ops
from sm_images.errors import StorageQuotaExceeded
from sm_images.models.billing_op import OP_EXPIRED, OP_INGEST

__all__ = [
    "INGEST_CLAIM",
    "Duplicate",
    "Slot",
    "drop_hold",
    "drop_slot",
    "hold_slot",
    "keep_hold",
    "release_after_rollback",
    "release_dropped",
    "safe_filename",
]

logger = logging.getLogger(__name__)

INGEST_CLAIM = timedelta(minutes=30)
"""How long an ingest owns its op: from the hold to the image insert."""


@dataclass(frozen=True)
class Duplicate:
    """The upload is an image the collection already holds."""

    image_id: uuid.UUID


@dataclass(frozen=True)
class Slot:
    """An image id and its original's key, with the intent already recorded,
    and - once sized (:func:`hold_slot`) - its storage hold and the op that
    took it, or ``refused`` when the plan's storage had no room for it."""

    image_id: uuid.UUID
    key: str
    hold: str | None = None
    refused: bool = False
    op: billing_ops.Claimed | None = None


class HoldTakenOver(Exception):  # noqa: N818 - reads as the condition
    """The ingest outlived its claim and a settler released the hold."""


def safe_filename(name: str | None, fallback: str = "upload") -> str:
    """The last path segment, without control characters, at most 255 characters."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    return base[:255] or fallback


async def hold_slot(factory: Any, tenant: str, slot: Slot, size: int) -> Slot:
    """Hold ``size`` bytes for the slot's original (committed), keyed by this attempt."""
    meter = billing.storage_meter(factory)
    if meter is None or size < 1:
        return slot
    key = billing.hold_key(slot.image_id, f"0-{uuid.uuid4().hex}")
    async with factory() as db:
        op = await billing_ops.open_op(
            db, OP_INGEST, slot.image_id, size, key, claim=INGEST_CLAIM, old=None
        )
        await finalize_session(db)
    try:
        hold = await billing.swap(factory, tenant, None, size, key, meter, not_after=op.not_after)
    except StorageQuotaExceeded as exc:
        async with factory() as db:
            await billing_ops.finish(db, op, None, f"{type(exc).__name__}: {exc}")
            await finalize_session(db)
        return replace(slot, refused=True)
    except billing.SwapExpired:  # expired or closed: the key's outcome, no hold
        async with factory() as db:
            await billing_ops.finish(db, op, None, OP_EXPIRED)
            await finalize_session(db)
        raise
    except Exception:
        async with factory() as db:  # whatever billing did is the settler's now
            await billing_ops.hand_back(db, op, factory)
            await finalize_session(db)
        raise
    return replace(slot, hold=hold.id, op=op)


async def keep_hold(db: Any, slot_op: billing_ops.Claimed | None, hold: str | None) -> None:
    """The image row names ``hold``: its op is done, with the row."""
    if slot_op is not None and not await billing_ops.finish(db, slot_op, hold):
        raise HoldTakenOver(slot_op.op_id)


async def drop_hold(db: Any, factory: Any, slot_op: billing_ops.Claimed | None) -> None:
    """Nothing keeps the hold: hand its op to the settler, which releases it."""
    await billing_ops.hand_back(db, slot_op, factory)


async def drop_slot(db: Any, factory: Any, slot: Slot | None) -> None:
    if slot is not None:
        await drop_hold(db, factory, slot.op)


async def release_dropped(factory: Any, dropped: list[billing_ops.Claimed]) -> None:
    """For a caller whose transaction is rolled back after taking holds: the
    insert's finish (or its in-transaction hand-back) went with it, so the op
    would stay claimed for :data:`INGEST_CLAIM` and a retry would hold twice.
    Hand each back again in a short transaction of its own - a no-op for one
    already handed back or finished - whose commit settles it, releasing the
    hold before any retry. Call it with no write transaction open on SQLite."""
    while dropped:
        async with factory() as db:
            await billing_ops.hand_back(db, dropped.pop(), factory)
            mark_written(db)  # Core DML: flag it, or finalize_session sees nothing
            await finalize_session(db)


async def release_after_rollback(factory: Any, acquired: list[billing_ops.Claimed]) -> None:
    """:func:`release_dropped` that never masks the caller's failure: an op
    whose hand-back fails here is the settler's once its claim expires."""
    try:
        await release_dropped(factory, acquired)
    except Exception:
        logger.exception("images.ingest.release_failed")
