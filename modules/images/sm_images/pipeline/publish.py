"""What a completed built-in step writes to the image, inside the completion.

Each runs in the completion transaction, after the run's own conditional
``UPDATE`` succeeded and while the image lock is held - so a stale worker never
gets here, and the values below are compared at store time, not load time.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, or_, select, update

from sm_images.models import Image, ObjectIntent, Rendition, StepRun
from sm_images.models.enums import LocationSource, StepStatus
from sm_images.processing.exif import ExifData
from sm_images.services import stats

__all__ = [
    "add_intents",
    "invalidate_renditions",
    "publish_display",
    "replace_renditions",
    "store_exif",
    "touch_image",
]

_SYNC = {"synchronize_session": False}
RENDITIONS = "renditions"


def _image(tenant: str, image_id: uuid.UUID) -> list[Any]:
    return [Image.id == image_id, Image.tenant_id == tenant, Image.is_deleted.is_(False)]


async def publish_display(
    db: Any, tenant: str, image_id: uuid.UUID, key: str, generation: int
) -> bool:
    """Swap in the new display copy, fenced on the generation it was made from."""
    stmt = (
        update(Image)
        .where(*_image(tenant, image_id), Image.display_generation == generation - 1)
        .values(display_key=key, display_generation=generation)
        .returning(Image.id)
        .execution_options(**_SYNC)
    )
    return (await db.execute(stmt)).first() is not None


async def invalidate_renditions(db: Any, tenant: str, image_id: uuid.UUID) -> None:
    """The display changed: renditions run again, whatever their state, and a
    rendition worker still holding the old lease can no longer complete."""
    await db.execute(
        update(StepRun)
        .where(
            StepRun.tenant_id == tenant, StepRun.image_id == image_id, StepRun.step == RENDITIONS
        )
        .values(
            status=StepStatus.PENDING,
            lease_token=None,
            lease_expires_at=None,
            error_code=None,
            error_message=None,
            output=None,
            started_at=None,
            finished_at=None,
        )
        .execution_options(**_SYNC)
    )


async def replace_renditions(
    db: Any,
    tenant: str,
    image_id: uuid.UUID,
    made: dict[str, tuple[str, int, int]],
    generation: int,
) -> list[str]:
    """Replace the image's rendition rows with ``made`` (size -> key, w, h), cut
    from display ``generation`` (stamped as ``source_generation``).

    Returns the keys no longer referenced, for deletion after the commit.
    """
    where = [Rendition.tenant_id == tenant, Rendition.image_id == image_id]
    old = (await db.execute(select(Rendition.storage_key).where(*where))).scalars().all()
    await db.execute(delete(Rendition).where(*where).execution_options(**_SYNC))
    for size, (key, width, height) in made.items():
        db.add(
            Rendition(
                image_id=image_id,
                size=size,
                storage_key=key,
                width=width,
                height=height,
                source_generation=generation,
            )
        )
    await db.flush()
    keep = {key for key, _, _ in made.values()}
    return [k for k in old if k not in keep]


async def touch_image(db: Any, tenant: str, image_id: uuid.UUID, now: datetime) -> None:
    """Move ``updated_at`` (the gallery shows when an image last changed)."""
    await db.execute(
        update(Image)
        .where(*_image(tenant, image_id))
        .values(updated_at=now)
        .execution_options(**_SYNC)
    )


async def add_intents(db: Any, keys: list[str]) -> None:
    """Objects about to become unreferenced: if deleting them after the commit
    fails, the janitor reaps them through these intents."""
    for key in dict.fromkeys(keys):
        await db.merge(ObjectIntent(key=key))


async def _location(db: Any, tenant: str, image_id: uuid.UUID, data: ExifData) -> bool:
    """EXIF coordinates, only over no location or an earlier EXIF one: a manual
    or imported location set between this step's load and now wins."""
    if data.lat is None or data.lng is None:
        return False
    old = (
        await db.execute(
            select(Image.collection_id, Image.lat, Image.lng).where(*_image(tenant, image_id))
        )
    ).first()
    stmt = (
        update(Image)
        .where(
            *_image(tenant, image_id),
            or_(Image.location_source.is_(None), Image.location_source == int(LocationSource.EXIF)),
        )
        .values(
            lat=data.lat,
            lng=data.lng,
            altitude=data.altitude,
            heading=data.heading,
            location_source=int(LocationSource.EXIF),
        )
        .returning(Image.id)
        .execution_options(**_SYNC)
    )
    if old is None or (await db.execute(stmt)).first() is None:
        return False
    before = None if old.lat is None or old.lng is None else (old.lat, old.lng)
    await stats.on_location_changed(db, old.collection_id, before, (data.lat, data.lng))
    return True


async def store_exif(db: Any, tenant: str, image_id: uuid.UUID, data: ExifData) -> bool:
    """Camera fields always; ``captured_at`` only if unset and zone-aware (a
    naive EXIF time has no zone, and is never stored as if it were UTC);
    location under the precedence rule. Returns whether the location changed."""
    camera = {
        k: v
        for k, v in (
            ("camera_make", data.make),
            ("camera_model", data.model),
            ("orientation", data.orientation),
        )
        if v is not None
    }
    if camera:
        await db.execute(
            update(Image)
            .where(*_image(tenant, image_id))
            .values(**camera)
            .execution_options(**_SYNC)
        )
    taken = data.captured_at
    if taken is not None and taken.utcoffset() is not None:
        await db.execute(
            update(Image)
            .where(*_image(tenant, image_id), Image.captured_at.is_(None))
            .values(captured_at=taken)
            .execution_options(**_SYNC)
        )
    return await _location(db, tenant, image_id, data)
