"""What the admin map routes (``endpoints/api/map.py``) and their anonymous
twins (``endpoints/public.py``) share: the ``…/points`` query parameters and
the points answer. Its own module, so neither surface imports the other."""

from __future__ import annotations

from typing import Any

from fastapi import Query, Request, Response

from sm_images import cache, constants
from sm_images.map import points

__all__ = ["BBox", "Cursor", "Limit", "points_response"]

Limit = Query(constants.POINTS_LIMIT_DEFAULT, ge=1)
"""Clamped to ``POINTS_LIMIT_MAX`` rather than refused: follow ``next_cursor``."""
BBox = Query(None, max_length=constants.BBOX_MAX_CHARS, description="minx,miny,maxx,maxy")
Cursor = Query(None, max_length=200)


async def points_response(
    request: Request,
    response: Response,
    db: Any,
    collection: Any,
    *,
    bbox: str | None,
    limit: int,
    cursor: str | None,
    twin: bool,
) -> dict[str, Any]:
    """Shared by both surfaces: the page, and Task 12's cache split (``no-cache``:
    points change with every processed image)."""
    box = points.parse_bbox(bbox)
    body = await points.page(db, collection, bbox=box, limit=limit, cursor=cursor)
    response.headers["Cache-Control"] = cache.cache_headers(
        request, collection, cache.DISPLAY, twin=twin, current=False
    )
    return body
