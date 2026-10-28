"""Streaming an image's bytes once its collection has been authorised (spec §5).

Both surfaces end here: the admin routes (``endpoints/api/serve.py``) after
``ImageCollectionView`` loaded the collection through the policy, and the
anonymous twins (``endpoints/public.py``) after ``public_collection``. The
order is the point:

1. **Which object** - the rendition row (joined with the image in one query),
   the display copy, or the original. Unknown image, unknown size or a missing
   object is the one 404 an absent id gets.
2. **May this caller have it** - ``…/original`` of a protected image needs
   :func:`~sm_images.access.can_view_original`, else 403. Checked before any
   validator is computed, so a refused caller cannot even probe for a 304.
3. **Cache headers**, then the conditional request (a 304 carries the same
   ``Cache-Control`` and ``ETag``), then ``Range``, then the body.

**Protected** means the original is not what everyone sees: the image has a
display copy, or its redaction is still pending (:mod:`sm_images.redaction`).

The gate only ever withholds bytes derived from the **original**. A display
copy, once published, was written by a display mutator and is already
redacted: it and the renditions cut from it (``source_generation`` equal to
the current ``display_generation``) are served whatever the mutator is doing
now - re-running, bumped, or uninstalled. Only an image with *no* display copy
is gated: while its redaction is pending, ``…/display`` (which would fall back
to the original) and its renditions (cut from the original) are a 404, the
portal's "thumbnail not available". A rendition is also a 404 unless it was
cut from the image's current display generation.

**Versions.** The display copy and each rendition carry a version
(:func:`sm_images.cache.version`); a request whose ``?v=`` is not it is served
the current bytes with ``no-cache`` (``sm_images.cache``). ``HEAD`` takes the
same path and sends the headers without opening the object.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from file_storage.contracts.service import StorageNotFoundError
from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import and_, select

from sm_images import cache, constants, redaction
from sm_images.access import can_view_original
from sm_images.errors import Forbidden, NotFound
from sm_images.models import Collection, Image, Rendition
from sm_images.ranges import RangeNotSatisfiable, parse_range
from sm_images.storage import ImageStore, store_for

__all__ = ["Target", "resolve", "serve"]


@dataclass(frozen=True)
class Target:
    key: str
    content_type: str
    protected: bool
    version: str | None = None
    """What ``?v=`` must say for the request to be "current"; ``None`` for an
    original, whose bytes never change."""


def _missing() -> NotFound:
    return NotFound(constants.NOT_FOUND_DETAIL)


async def _load(db: Any, collection: Collection, image_id: uuid.UUID, size: str | None) -> Any:
    """The image (and the requested rendition) in one query."""
    where = (Image.id == image_id, Image.collection_id == collection.id)
    if size is None:
        found = (await db.execute(select(Image).where(*where))).scalars().first()
        return None if found is None else (found, None)
    on = and_(Rendition.image_id == Image.id, Rendition.size == size)
    stmt = select(Image, Rendition).outerjoin(Rendition, on).where(*where)
    row = (await db.execute(stmt)).first()
    return None if row is None else (row[0], row[1])


async def resolve(
    db: Any, collection: Collection, image_id: uuid.UUID, route: str, size: str | None
) -> tuple[Image, Target]:
    loaded = await _load(db, collection, image_id, size if route == cache.RENDITION else None)
    if loaded is None:
        raise _missing()
    image, rendition = loaded
    # Only original-derived bytes can be unredacted; a display copy never is.
    pending = image.display_key is None and await redaction.pending(db, collection, image)
    if route == cache.RENDITION:
        if rendition is None or pending or rendition.source_generation != image.display_generation:
            raise _missing()
        v = cache.version(rendition.source_generation, rendition.storage_key)
        return image, Target(rendition.storage_key, constants.DISPLAY_CONTENT_TYPE, False, v)
    if route == cache.DISPLAY:
        if pending:
            raise _missing()
        key = image.display_key or image.storage_key
        kind = constants.DISPLAY_CONTENT_TYPE if image.display_key else image.content_type
        return image, Target(key, kind, False, cache.version(image.display_generation, key))
    protected = image.display_key is not None or pending
    return image, Target(image.storage_key, image.content_type, protected)


async def _closing(source: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Relay *source*, and close it even when the client goes away mid-body."""
    try:
        async for chunk in source:
            yield chunk
    finally:
        aclose = getattr(source, "aclose", None)
        if aclose is not None:
            await aclose()


async def _respond(
    request: Request, store: ImageStore, target: Target, policy: str, ranged: bool
) -> Response:
    head = await store.head(target.key)
    if head is None:
        raise _missing()
    size = head[0]
    tag = cache.etag(target.key, size)
    headers = {"ETag": tag, "Cache-Control": policy, "X-Content-Type-Options": "nosniff"}
    if ranged:
        headers["Accept-Ranges"] = "bytes"
    if cache.not_modified(request.headers.get("if-none-match"), tag):
        return Response(status_code=304, headers=headers)
    wanted = None
    if ranged and cache.if_range_ok(request.headers.get("if-range"), tag):
        try:
            wanted = parse_range(request.headers.get("range"), size)
        except RangeNotSatisfiable:
            return Response(
                status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"}
            )
    status, length = 200, size
    if wanted is not None:
        status, length = 206, wanted.length
        headers["Content-Range"] = f"bytes {wanted.start}-{wanted.end}/{size}"
    headers["Content-Length"] = str(length)
    if request.method == "HEAD":
        return Response(status_code=status, media_type=target.content_type, headers=headers)
    try:
        if wanted is None:
            body = await store.stream(target.key)
        else:
            body = await store.stream_range(target.key, wanted.start, wanted.end)
    except StorageNotFoundError:
        raise _missing() from None
    return StreamingResponse(
        _closing(body), status_code=status, media_type=target.content_type, headers=headers
    )


async def serve(
    request: Request,
    db: Any,
    collection: Collection,
    image_id: uuid.UUID,
    who: ResourcePrincipal,
    route: str,
    *,
    size: str | None = None,
    twin: bool,
) -> Response:
    """Authorised bytes of *route* for *image_id*, inside an authorised *collection*."""
    image, target = await resolve(db, collection, image_id, route, size)
    if route == cache.ORIGINAL and not can_view_original(
        who, image, collection, protected=target.protected
    ):
        raise Forbidden(constants.ORIGINAL_FORBIDDEN_DETAIL)
    current = target.version is not None and request.query_params.get("v") == target.version
    policy = cache.cache_headers(
        request, collection, route, twin=twin, protected=target.protected, current=current
    )
    ranged = route != cache.RENDITION
    return await _respond(request, store_for(request.app), target, policy, ranged)
