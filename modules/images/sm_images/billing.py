"""Storage billing seams (plan decision 10). Task 25 wires them to ``billing``.

Until then every hook is a no-op, so the janitor already calls it at the right
point: after the purged rows are deleted, in the same transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

__all__ = ["StorageHold", "release_storage"]

StorageHold = tuple[uuid.UUID, str | None, int]
"""``(image_id, storage_hold_id, storage_bytes)`` of a hard-deleted image."""


async def release_storage(db: Any, holds: Sequence[StorageHold]) -> None:
    """Release the storage-gauge holds of hard-deleted images (no-op for now)."""
