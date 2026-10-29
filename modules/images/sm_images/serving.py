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

A display copy written by the collection's current display mutator
(``Image.display_step``, any version of it) is redacted: it and the renditions
cut from it (``source_generation`` equal to the current
``display_generation``) are served whatever that mutator is doing now -
re-running, bumped, or uninstalled. Anything else - no display copy, or one
another step wrote (a crop, before an anonymiser was enabled) - is gated:
while redaction is pending, ``…/display`` and its renditions are a 404, the
portal's "thumbnail not available", and the original is protected. A
rendition is also a 404 unless it was cut from the current display
generation.

**Caching.** Every answer is ``no-cache`` with a strong ETag
(``sm_images.cache``), and the 304 for ``If-None-Match`` is decided only here,
after the access and redaction checks above, so a revoked image stops
answering conditional requests too. ``?v=`` in a URL only busts caches: the
current bytes are served whatever it says. ``HEAD`` takes the same path and
sends the headers without opening the object.
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

from sm_images import cache, constants, errors, redaction
from sm_images.access import can_view_original
from sm_images.errors import Forbidden, NotFound
from sm_images.models import Collection, Image, Rendition
from sm_images.ranges import RangeNotSatisfiable, parse_range
from sm_images.services.viewer_stats import viewer_only
from sm_images.storage import ImageStore, store_for

__all__ = ["Target", "resolve", "serve", "serve_map"]


@dataclass(frozen=True)
class Target:
    key: str
    content_type: str
    protected: bool
    withheld: bool = False
    """Redaction is still pending: the picture itself may not be shown yet."""


def _missing(twin: bool = True) -> Exception:
    """The 404 of every "no such picture". On the authenticated routes it is the
    one the framework's ``RequiresResource`` raises for an unknown id (so the
    host negotiates JSON, HTML and Inertia the same way, ``Vary`` included); a
    module ``NotFound`` would render differently and tell a withheld image from
    an absent one. The anonymous twin's absent id is the module's own."""
    return NotFound(constants.NOT_FOUND_DETAIL) if twin else errors.absent()


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
    db: Any,
    collection: Collection,
    image_id: uuid.UUID,
    route: str,
    size: str | None,
    *,
    twin: bool = True,
) -> tuple[Image, Target]:
    loaded = await _load(db, collection, image_id, size if route == cache.RENDITION else None)
    if loaded is None:
        raise _missing(twin)
    image, rendition = loaded
    # A display copy the current mutator wrote is redacted; anything else -
    # the original, or a copy from another step - waits for the gate.
    trusted = redaction.trusts_display(collection, image)
    pending = not trusted and await redaction.pending(db, collection, image)
    if route == cache.RENDITION:
        if rendition is None or pending or rendition.source_generation != image.display_generation:
            raise _missing(twin)
        return image, Target(rendition.storage_key, constants.DISPLAY_CONTENT_TYPE, False)
    if route == cache.DISPLAY:
        if pending:
            raise _missing(twin)
        key = image.display_key or image.storage_key
        kind = constants.DISPLAY_CONTENT_TYPE if image.display_key else image.content_type
        return image, Target(key, kind, False)
    protected = image.display_key is not None or pending
    return image, Target(image.storage_key, image.content_type, protected, withheld=pending)


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
    request: Request,
    store: ImageStore,
    target: Target,
    policy: str,
    ranged: bool,
    twin: bool = True,
) -> Response:
    head = await store.head(target.key)
    if head is None:
        raise _missing(twin)
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
        raise _missing(twin) from None
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
    image, target = await resolve(db, collection, image_id, route, size, twin=twin)
    # A viewer's gate comes first: a withheld image is the 404 an absent id gets,
    # not a 403 that says it exists.
    if route == cache.ORIGINAL and target.withheld and await viewer_only(db, who, collection):
        raise _missing(twin)
    if route == cache.ORIGINAL and not can_view_original(
        who, image, collection, protected=target.protected
    ):
        raise Forbidden(constants.ORIGINAL_FORBIDDEN_DETAIL)
    policy = cache.cache_headers(request, collection, route, twin=twin, protected=target.protected)
    ranged = route != cache.RENDITION
    return await _respond(request, store_for(request.app), target, policy, ranged, twin)


async def serve_map(request: Request, collection: Collection, *, twin: bool) -> Response:
    """The collection's PMTiles archive (``sm_images.map``), already authorised.

    ``collection`` was just re-read through the policy (admin) or as public
    (twin), so a visibility change stops the next range request. No archive -
    never built, or withdrawn (a visibility change, a removed point, a new
    redaction gate) and not rebuilt yet - is the plain 404, and so is an
    archive built under another redaction gate than the collection has now
    (``redaction.gate_key``: a mutator installed, removed or bumped since):
    it may place images that are pending again.

    Ranges as above; the ETag digests the archive's key, which names its
    build generation, so a rebuild is a new ETag and a stale
    ``If-Range`` gets the whole new archive rather than a splice of two.
    ``no-cache`` on both surfaces (Task 12's ``public``/``private`` split):
    the URL is stable, so every cache revalidates, and a withdrawn map stops
    being served by caches too. An archive that predates changes a rebuild
    is pending for (``schedule.rebuild_pending``) carries ``X-Map-Stale: 1``.
    """
    if not collection.map_key or collection.map_policy_rev != redaction.gate_key(collection):
        raise _missing(twin)
    policy = cache.cache_headers(request, collection, cache.DISPLAY, twin=twin)
    target = Target(collection.map_key, constants.PMTILES_CONTENT_TYPE, False)
    response = await _respond(request, store_for(request.app), target, policy, True, twin)
    from sm_images.map.schedule import rebuild_pending

    if rebuild_pending(collection):  # older than the points: the client reads those instead
        response.headers["X-Map-Stale"] = "1"
    return response
