"""``GET /collections/{id}/points`` and ``GET|HEAD …/map.pmtiles`` (spec §5).

``CollectionView`` re-reads the collection through the policy on every request
- every range request of a map viewer included - so a collection the caller
may no longer see is the 404 an unknown id gets. The anonymous twins are in
:mod:`sm_images.endpoints.public`. Both answers depend on who asks, so both
are ``private``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from simple_module_db.deps import get_db

from sm_images import cache, constants, serving
from sm_images.access import CollectionView
from sm_images.deps import require_view
from sm_images.map import points

router = APIRouter(prefix="/collections", tags=["images-map"])

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


@router.get("/{collection_id}/points", dependencies=[require_view])
async def collection_points(
    request: Request,
    response: Response,
    collection: CollectionView,
    db: Any = Depends(get_db),
    bbox: str | None = BBox,
    limit: int = Limit,
    cursor: str | None = Cursor,
) -> dict[str, Any]:
    """GeoJSON points of the collection: ``id``, ``captured_at``, ``group_id``."""
    return await points_response(
        request, response, db, collection, bbox=bbox, limit=limit, cursor=cursor, twin=False
    )


async def collection_map(request: Request, collection: CollectionView) -> Response:
    """The collection's PMTiles archive, with ``Range``."""
    return await serving.serve_map(request, collection, twin=False)


_MAP = "/{collection_id}/map.pmtiles"
router.head(_MAP, include_in_schema=False, response_model=None, dependencies=[require_view])(
    collection_map
)
router.get(_MAP, response_model=None, dependencies=[require_view])(collection_map)
