"""What ingest hands around: a reserved :class:`Slot` (intent and storage hold
taken before the caller's transaction writes), a :class:`Duplicate` answer,
and the file name a row keeps.

The storage hold follows ``sm_images.billing``'s order: reserved here, before
any write; committed after the caller's commit when the image is kept
(:func:`keep_hold`); released after it when not (:func:`drop_hold`). A
rollback discards both queued calls and the ``held`` hold lapses by itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any

from sm_images import billing
from sm_images.errors import StorageQuotaExceeded

__all__ = ["Duplicate", "Slot", "drop_hold", "hold_slot", "keep_hold", "safe_filename"]


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
    """Reserve ``size`` bytes for the slot's original (storage generation 0)."""
    try:
        hold = await billing.reserve(factory, tenant, size, billing.hold_key(slot.image_id, 0))
    except StorageQuotaExceeded:
        return replace(slot, refused=True)
    return replace(slot, hold=hold)


def keep_hold(db: Any, factory: Any, hold: str | None) -> None:
    """The image row holds ``hold``: commit it once ``db`` commits."""
    if hold is not None:
        billing.on_commit(db, billing.settle, factory, hold, None)


def drop_hold(db: Any, factory: Any, hold: str | None) -> None:
    """Nothing kept ``hold``: release it once ``db`` commits."""
    if hold is not None:
        billing.on_commit(db, billing.release, factory, [hold])
