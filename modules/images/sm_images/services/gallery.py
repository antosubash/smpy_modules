"""A collection's images: the cursor list, one image, its manual location, delete.

The caller has already loaded the collection through the access policy (the
routes' ``RequiresResource`` dependencies), so every statement here is pinned
to that collection's id and needs no policy of its own. The tenant filter and
the soft-delete filter come from the framework.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import exists, func, select, update

from sm_images import constants
from sm_images.errors import Conflict, NotFound
from sm_images.map import revoke as map_revoke
from sm_images.map import schedule as map_schedule
from sm_images.models import (
    Collection,
    Image,
    LocationSource,
    PromptResult,
    ReviewStatus,
    StepRun,
    StepStatus,
)
from sm_images.services import cursor as cursors
from sm_images.services import stats

__all__ = ["Filters", "delete", "get", "list_page", "set_location"]

_MOVED = "The image's location changed while it was being edited; reload and try again"


@dataclass(frozen=True)
class Filters:
    has_location: bool | None = None
    step: str | None = None
    step_status: StepStatus | None = None
    review_status: ReviewStatus | None = None
    group: uuid.UUID | None = None


def _where(stmt: Any, f: Filters) -> Any:
    if f.has_location is not None:
        stmt = stmt.where(Image.lat.is_not(None) if f.has_location else Image.lat.is_(None))
    if f.step is not None or f.step_status is not None:
        run = select(StepRun.id).where(StepRun.image_id == Image.id)
        if f.step is not None:
            run = run.where(StepRun.step == f.step)
        if f.step_status is not None:
            run = run.where(StepRun.status == f.step_status)
        stmt = stmt.where(exists(run))
    if f.review_status is not None:
        reviewed = select(PromptResult.id).where(
            PromptResult.image_id == Image.id, PromptResult.review_status == f.review_status
        )
        stmt = stmt.where(exists(reviewed))
    if f.group is not None:
        stmt = stmt.where(Image.group_id == f.group)
    return stmt


async def list_page(
    db: Any,
    collection: Collection,
    filters: Filters,
    *,
    limit: int = constants.PAGE_DEFAULT,
    cursor: str | None = None,
) -> tuple[list[Image], str | None, int | None]:
    """``(rows, next_cursor, total)``, newest first; ``total`` on the first page only."""
    stmt = _where(select(Image).where(Image.collection_id == collection.id), filters)
    total = None
    if cursor is None:
        counted = select(func.count()).select_from(stmt.subquery())
        total = int((await db.execute(counted)).scalar_one())
    else:
        stmt = stmt.where(cursors.seek(Image.created_at, Image.id, cursor))
    stmt = stmt.order_by(Image.created_at.desc(), Image.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    token = cursors.encode(rows[-1].created_at, rows[-1].id) if more else None
    return rows, token, total


async def get(db: Any, collection: Collection, image_id: uuid.UUID) -> Image:
    stmt = select(Image).where(Image.id == image_id, Image.collection_id == collection.id)
    found = (await db.execute(stmt)).scalars().first()
    if found is None:
        raise NotFound(constants.NOT_FOUND_DETAIL)
    return found


async def set_location(
    db: Any, collection: Collection, image: Image, lat: float | None, lng: float | None
) -> Image:
    """A manual location (or none), as a compare-and-set on the coordinates read.

    A worker writing an EXIF location between our read and this write makes the
    update match nothing: a 409, never a silently lost write. Stats follow in the
    same transaction; moving or clearing a point recomputes the box (it cannot
    shrink incrementally).
    """
    old = None if image.lat is None or image.lng is None else (image.lat, image.lng)
    new = None if lat is None or lng is None else (lat, lng)
    source = None if new is None else LocationSource.MANUAL
    result = await db.execute(
        update(Image)
        .where(
            Image.id == image.id,
            Image.collection_id == collection.id,
            Image.lat.is_not_distinct_from(image.lat),
            Image.lng.is_not_distinct_from(image.lng),
        )
        .values(lat=lat, lng=lng, location_source=source)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise Conflict(_MOVED)
    if old is None:
        await stats.on_location_changed(db, collection.id, old, new)
    elif old != new:
        await stats.recompute(db, collection.id)
    if old is not None and new is None:  # the point leaves the published map now
        await map_revoke.point_removed(db, collection)
    elif old != new:  # a move never waits for the map's rebuild threshold
        await map_schedule.changed(db, collection.id, urgent=True)
    await db.refresh(image)
    return image


async def delete(db: Any, collection: Collection, image: Image) -> None:
    """Soft delete (the janitor purges after the grace period); stats recomputed,
    and a located image's point taken off the map in this transaction: the
    archive is withdrawn and any build in flight fenced (``map.revoke``)."""
    located = image.lat is not None
    await db.delete(image)
    await db.flush()
    await stats.recompute(db, collection.id)
    if located:
        await map_revoke.point_removed(db, collection)
