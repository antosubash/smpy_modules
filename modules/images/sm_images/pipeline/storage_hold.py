"""The storage gauge at the executor's fenced publication (plan decision 10).

A step that publishes objects (a display copy, a rendition set) changes what
the image stores, so ``Image.storage_bytes`` and its hold move with it:

1. **Before the completion** (:func:`reserve`): the new total - the original,
   the display copy and the renditions, with this attempt's objects in place
   of the ones they replace - is reserved as a ``held`` hold, keyed by the
   attempt's nonce. Not inside the completion transaction: billing writes in
   its own transaction, which on file-backed SQLite would wait on the image
   lock the completion holds (the object intents' rule, ``finish.stage``). A
   refusal is ``StorageQuotaExceeded``: the caller deletes the staged objects
   and fails the step ``quota_exceeded``; nothing is published.
2. **In the completion, under the image lock and after the fenced writes**
   (:func:`record`): the total is recomputed from the rows. If it is not what
   was reserved (another publication moved it in between) the completion is
   treated like a lost fence - rolled back and planned again. Otherwise
   ``storage_bytes`` and ``storage_hold_id`` are written, and the new hold's
   commit and the old one's release are queued for after the commit
   (``sm_images.billing.settle``).
3. **A completion that keeps nothing** releases the new hold (:func:`unhold`).

Without billing the hold is ``None`` and only ``storage_bytes`` is written.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, update

from sm_images import billing
from sm_images.models import Image, Rendition
from sm_images.pipeline.runtime import Runtime

__all__ = ["Planned", "record", "reserve", "total", "unhold"]


@dataclass(frozen=True)
class Planned:
    total: int
    hold: str | None


async def _parts(db: Any, tenant: str, image_id: uuid.UUID) -> tuple[int, int, int, str | None]:
    """``(original, display copy, renditions, hold)`` of the image's stored bytes."""
    image = (
        await db.execute(
            select(Image.size_bytes, Image.display_bytes, Image.storage_hold_id).where(
                Image.id == image_id, Image.tenant_id == tenant
            )
        )
    ).one()
    rendered = await db.execute(
        select(func.coalesce(func.sum(Rendition.size_bytes), 0)).where(
            Rendition.image_id == image_id, Rendition.tenant_id == tenant
        )
    )
    return int(image[0]), int(image[1]), int(rendered.scalar_one()), image[2]


async def total(db: Any, tenant: str, image_id: uuid.UUID) -> int:
    original, display, renditions, _ = await _parts(db, tenant, image_id)
    return original + display + renditions


async def reserve(runtime: Runtime, loaded: Any, staged: Any) -> Planned | None:
    """Reserve the total the image will store once ``staged`` is published;
    ``None`` when the step stages no object."""
    if not staged.keys:
        return None
    async with runtime.session_factory() as db:
        original, display, renditions, _ = await _parts(db, loaded.tenant, loaded.image_id)
    if staged.display_key is not None:
        display = staged.display_bytes
    if staged.renditions:
        renditions = sum(r[3] for r in staged.renditions.values())
    planned = original + display + renditions
    key = billing.hold_key(loaded.image_id, staged.attempt)
    hold = await billing.reserve(runtime.session_factory, loaded.tenant, planned, key)
    return Planned(planned, hold)


async def record(db: Any, runtime: Runtime, loaded: Any, planned: Planned | None) -> bool:
    """Write the image's new total (under the lock, after the publication);
    ``False`` when a hold was reserved for another total - the caller must
    roll back."""
    if planned is None:
        return True
    original, display, renditions, old = await _parts(db, loaded.tenant, loaded.image_id)
    now = original + display + renditions
    if planned.hold is not None and now != planned.total:
        return False
    values: dict[str, Any] = {"storage_bytes": now}
    if planned.hold is not None:
        values["storage_hold_id"] = planned.hold
        billing.on_commit(db, billing.settle, runtime.session_factory, planned.hold, old)
    await db.execute(
        update(Image)
        .where(Image.id == loaded.image_id, Image.tenant_id == loaded.tenant)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return True


async def unhold(runtime: Runtime, planned: Planned | None) -> None:
    """Nothing was published: give the reserved capacity back."""
    if planned is not None and planned.hold is not None:
        await billing.release(runtime.session_factory, [planned.hold])
