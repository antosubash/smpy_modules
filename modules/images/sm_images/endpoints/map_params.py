"""What the admin map routes (``endpoints/api/map.py``) and their anonymous
twins (``endpoints/public.py``) share: the ``…/points`` query parameters and
the points answer. Its own module, so neither surface imports the other."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Query, Request, Response
from fastapi.encoders import jsonable_encoder

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
) -> Any:
    """Shared by both surfaces: the page, and Task 12's cache split (``no-cache``:
    points change with every processed image).

    Revalidated like the byte routes (``sm_images.cache``): a strong ETag that
    digests the answer itself, so it changes with any point and differs
    between a viewer's gated page and an editor's raw one. The caller's
    dependencies have already re-checked access, and the page was built
    through the redaction gate, so a 304 is only ever sent for an answer the
    caller may see now."""
    box = points.parse_bbox(bbox)
    body = await points.page(db, collection, bbox=box, limit=limit, cursor=cursor)
    policy = cache.cache_headers(request, collection, cache.DISPLAY, twin=twin)
    encoded = json.dumps(jsonable_encoder(body), sort_keys=True, separators=(",", ":"))
    tag = cache.etag(encoded, len(encoded))
    if cache.not_modified(request.headers.get("if-none-match"), tag):
        return Response(status_code=304, headers={"ETag": tag, "Cache-Control": policy})
    response.headers["Cache-Control"] = policy
    response.headers["ETag"] = tag
    return body
