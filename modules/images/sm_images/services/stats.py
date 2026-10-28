"""Collection counters and bounding box.

The incremental helpers are single SQL ``UPDATE``s in the **caller's**
transaction: they commit with the image row they describe, take no read-modify-
write round trip (so concurrent uploads do not lose increments), and are
portable - ``CASE`` stands in for Postgres' ``greatest``/``least``, which
SQLite does not have as two-argument scalars.

They only ever *grow* the box and clamp counters at zero. A removal or a lost
location cannot shrink a box incrementally; :func:`recompute` does that, from
one aggregate, and is what the reconcile task and the delete paths call.

Coordinates are ``lat, lng``; the box is ``(minx, miny, maxx, maxy)`` =
``(lng, lat, lng, lat)``. ``(0, 0)`` is a valid location.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import case, func, select, update

from sm_images.models import Collection, Image

__all__ = ["on_image_added", "on_image_removed", "on_location_changed", "recompute"]

Coord = tuple[float, float]


def _bump(column: Any, delta: int) -> Any:
    """``column + delta``, never below zero."""
    return case((column + delta < 0, 0), else_=column + delta)


def _extend(lat: float, lng: float) -> dict[str, Any]:
    c = Collection
    return {
        "bbox_minx": case(
            (c.bbox_minx.is_(None), lng), (c.bbox_minx > lng, lng), else_=c.bbox_minx
        ),
        "bbox_miny": case(
            (c.bbox_miny.is_(None), lat), (c.bbox_miny > lat, lat), else_=c.bbox_miny
        ),
        "bbox_maxx": case(
            (c.bbox_maxx.is_(None), lng), (c.bbox_maxx < lng, lng), else_=c.bbox_maxx
        ),
        "bbox_maxy": case(
            (c.bbox_maxy.is_(None), lat), (c.bbox_maxy < lat, lat), else_=c.bbox_maxy
        ),
    }


async def _apply(db: Any, collection_id: uuid.UUID, values: dict[str, Any]) -> None:
    await db.execute(
        update(Collection)
        .where(Collection.id == collection_id)
        .values(**values)
        .execution_options(synchronize_session=False)
    )


def _located(lat: float | None, lng: float | None) -> bool:
    return lat is not None and lng is not None


async def on_image_added(
    db: Any, collection_id: uuid.UUID, lat: float | None, lng: float | None
) -> None:
    values: dict[str, Any] = {"image_count": _bump(Collection.image_count, 1)}
    if lat is not None and lng is not None:
        values["located_count"] = _bump(Collection.located_count, 1)
        values.update(_extend(lat, lng))
    await _apply(db, collection_id, values)


async def on_image_removed(
    db: Any, collection_id: uuid.UUID, lat: float | None, lng: float | None
) -> None:
    values: dict[str, Any] = {"image_count": _bump(Collection.image_count, -1)}
    if _located(lat, lng):
        values["located_count"] = _bump(Collection.located_count, -1)
    await _apply(db, collection_id, values)


async def on_location_changed(
    db: Any, collection_id: uuid.UUID, old: Coord | None, new: Coord | None
) -> None:
    """``old``/``new`` are ``(lat, lng)`` or ``None`` for no location."""
    values: dict[str, Any] = {}
    if old is None and new is not None:
        values["located_count"] = _bump(Collection.located_count, 1)
    elif old is not None and new is None:
        values["located_count"] = _bump(Collection.located_count, -1)
    if new is not None:
        values.update(_extend(*new))
    if values:
        await _apply(db, collection_id, values)


async def recompute(db: Any, collection_id: uuid.UUID) -> None:
    """Counts and box from the images themselves (trashed ones excluded by the
    soft-delete filter). The only way the box shrinks."""
    row = (
        await db.execute(
            select(
                func.count(Image.id),
                func.count(Image.lat),
                func.min(Image.lng),
                func.min(Image.lat),
                func.max(Image.lng),
                func.max(Image.lat),
            ).where(Image.collection_id == collection_id)
        )
    ).one()
    total, located, minx, miny, maxx, maxy = row
    await _apply(
        db,
        collection_id,
        {
            "image_count": total,
            "located_count": located,
            "bbox_minx": minx,
            "bbox_miny": miny,
            "bbox_maxx": maxx,
            "bbox_maxy": maxy,
        },
    )
