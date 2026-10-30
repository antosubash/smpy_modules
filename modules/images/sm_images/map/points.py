"""Which images a map may place, and the ``…/points`` GeoJSON page.

A point is an image of the (already authorised) collection that is not
trashed, has a real coordinate, and whose picture may be shown
(:func:`sm_images.access.redaction.ready_clause`): an image still waiting for its
blur is not on the map, the portal's privacy gate. The same statement feeds
the PMTiles build (:mod:`sm_images.map.build`), so the archive and the points
never disagree about who is on the map.

A point carries ``id``, ``captured_at`` and ``group_id`` - never a filename,
properties or anything else of the image. The caller authorises the
collection; nothing here checks access.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select

from sm_images.access import redaction
from sm_images.core import constants
from sm_images.core.errors import Invalid
from sm_images.models import Collection, Image
from sm_images.services import cursor as cursors

__all__ = ["BBox", "check_bbox", "feature", "located", "page", "parse_bbox"]

BBox = tuple[float, float, float, float]
"""``(minx, miny, maxx, maxy)`` in degrees; ``minx > maxx`` crosses the antimeridian."""


def _bad() -> Invalid:
    return Invalid(constants.BAD_BBOX_DETAIL)


def check_bbox(box: tuple[float, ...]) -> BBox:
    if len(box) != 4 or not all(math.isfinite(v) for v in box):
        raise _bad()
    minx, miny, maxx, maxy = box
    if not (-180 <= minx <= 180 and -180 <= maxx <= 180):
        raise _bad()
    if not (-90 <= miny <= maxy <= 90):
        raise _bad()
    return float(minx), float(miny), float(maxx), float(maxy)


def parse_bbox(raw: str | None) -> BBox | None:
    """``"minx,miny,maxx,maxy"`` -> a checked box; ``None`` for no box. 422 otherwise."""
    if raw is None or not raw.strip():
        return None
    try:
        values = tuple(float(part) for part in raw.split(","))
    except ValueError:
        raise _bad() from None
    return check_bbox(values)


def _in_box(box: BBox) -> Any:
    minx, miny, maxx, maxy = box
    lat = and_(Image.lat >= miny, Image.lat <= maxy)
    if minx <= maxx:
        return and_(lat, Image.lng >= minx, Image.lng <= maxx)
    return and_(lat, or_(Image.lng >= minx, Image.lng <= maxx))


def located(collection: Collection, *columns: Any) -> Any:
    """``SELECT columns`` (default: the point's) over the images of *collection*
    that may be placed. ``ready_clause`` reads the collection's config now."""
    cols = columns or (Image.id, Image.lat, Image.lng, Image.captured_at, Image.group_id)
    return select(*cols).where(
        Image.collection_id == collection.id,
        Image.is_deleted.is_(False),
        Image.lat.between(-90, 90),
        Image.lng.between(-180, 180),
        redaction.ready_clause(collection),
    )


def feature(
    image_id: uuid.UUID,
    lat: float,
    lng: float,
    captured_at: datetime | None,
    group_id: uuid.UUID | None,
) -> dict[str, Any]:
    """One GeoJSON point: ``[lng, lat]`` and the three properties, nothing else."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": {
            "id": str(image_id),
            "captured_at": captured_at.isoformat() if captured_at else None,
            "group_id": str(group_id) if group_id else None,
        },
    }


async def page(
    db: Any,
    collection: Collection,
    *,
    bbox: BBox | None = None,
    limit: int = constants.POINTS_LIMIT_DEFAULT,
    cursor: str | None = None,
) -> dict[str, Any]:
    """A ``FeatureCollection`` of up to ``limit`` points (clamped to
    ``POINTS_LIMIT_MAX``), newest first, with ``next_cursor`` for the rest."""
    limit = max(1, min(int(limit), constants.POINTS_LIMIT_MAX))
    stmt = located(
        collection,
        Image.id,
        Image.lat,
        Image.lng,
        Image.captured_at,
        Image.group_id,
        Image.created_at,
    )
    if bbox is not None:
        stmt = stmt.where(_in_box(bbox))
    if cursor:
        stmt = stmt.where(cursors.seek(Image.created_at, Image.id, cursor))
    stmt = stmt.order_by(Image.created_at.desc(), Image.id.desc()).limit(limit + 1)
    rows, token = cursors.cut(list((await db.execute(stmt)).all()), limit)
    return {
        "type": "FeatureCollection",
        "features": [feature(*row[:5]) for row in rows],
        "next_cursor": token,
    }
