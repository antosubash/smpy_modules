"""What ingest hands around: a reserved :class:`Slot` (intent and storage hold
taken before the caller's transaction writes), a :class:`Duplicate` answer,
and the file name a row keeps.

The storage hold follows ``sm_images.billing``'s order: reserved here, before
any write, under a key of this attempt's own (a concurrent attempt for the same
image - two ``complete`` calls - never shares it, so a loser releases only its
own hold); its ``commit`` written to the outbox with the image row
(:func:`keep_hold`), or its ``release`` when nothing kept it
(:func:`drop_hold`). A rollback discards both and the ``held`` hold lapses.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any

from sm_images import billing, billing_ops
from sm_images.errors import StorageQuotaExceeded
from sm_images.models.billing_op import OP_COMMIT, OP_RELEASE

__all__ = [
    "Duplicate",
    "Slot",
    "drop_hold",
    "drop_slot",
    "hold_slot",
    "keep_hold",
    "safe_filename",
]


@dataclass(frozen=True)
class Duplicate:
    """The upload is an image the collection already holds."""

    image_id: uuid.UUID


@dataclass(frozen=True)
class Slot:
    """An image id and its original's key, with the intent already recorded,
    and - once sized (:func:`hold_slot`) - its storage hold, or ``refused``
    when the plan's storage had no room for it."""

    image_id: uuid.UUID
    key: str
    hold: str | None = None
    refused: bool = False


def safe_filename(name: str | None, fallback: str = "upload") -> str:
    """The last path segment, without control characters, at most 255 characters."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    return base[:255] or fallback


async def hold_slot(factory: Any, tenant: str, slot: Slot, size: int) -> Slot:
    """Reserve ``size`` bytes for the slot's original, keyed by this attempt."""
    key = billing.hold_key(slot.image_id, f"0-{uuid.uuid4().hex}")
    try:
        hold = await billing.reserve(factory, tenant, size, key)
    except StorageQuotaExceeded:
        return replace(slot, refused=True)
    return replace(slot, hold=None if hold is None else hold.id)


async def keep_hold(
    db: Any, factory: Any, image_id: uuid.UUID, hold: str | None, size: int
) -> None:
    """The image row holds ``hold``: its ``commit``, with the row."""
    if hold is not None:
        await billing_ops.add(
            db, OP_COMMIT, image_id=image_id, hold_id=hold, quantity=size, factory=factory
        )


async def drop_hold(db: Any, factory: Any, image_id: uuid.UUID, hold: str | None) -> None:
    """Nothing kept ``hold``: its ``release``, with the caller's transaction."""
    if hold is not None:
        await billing_ops.add(db, OP_RELEASE, image_id=image_id, hold_id=hold, factory=factory)


async def drop_slot(db: Any, factory: Any, slot: Slot | None) -> None:
    if slot is not None:
        await drop_hold(db, factory, slot.image_id, slot.hold)
