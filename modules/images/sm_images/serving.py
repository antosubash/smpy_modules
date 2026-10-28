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
display copy, *or* the collection enables a display mutator that has not
settled (completed or skipped) for this image - until it has, the original is
the unredacted picture, so ``…/display`` withholds it (404, the portal's
"thumbnail not available") rather than falling back to it.
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

from sm_images import cache, constants
from sm_images.access import can_view_original
from sm_images.errors import Forbidden, NotFound
from sm_images.models import Collection, Image, Rendition, StepRun
from sm_images.models.enums import StepStatus
from sm_images.ranges import RangeNotSatisfiable, parse_range
from sm_images.storage import ImageStore, store_for

__all__ = ["Target", "serve"]

_SETTLED = (StepStatus.COMPLETED, StepStatus.SKIPPED)


@dataclass(frozen=True)
class Target:
    key: str
    content_type: str
    protected: bool


def _missing() -> NotFound:
    return NotFound(constants.NOT_FOUND_DETAIL)


async def _load(db: Any, collection: Collection, image_id: uuid.UUID, size: str | None) -> Any:
    """The image (and the requested rendition's key) in one query."""
    where = (Image.id == image_id, Image.collection_id == collection.id)
    if size is None:
        found = (await db.execute(select(Image).where(*where))).scalars().first()
        return None if found is None else (found, None)
    on = and_(Rendition.image_id == Image.id, Rendition.size == size)
    stmt = select(Image, Rendition.storage_key).outerjoin(Rendition, on).where(*where)
    row = (await db.execute(stmt)).first()
    return None if row is None else (row[0], row[1])


def _mutators(collection: Collection) -> list[str]:
    """Enabled steps of *collection* that write a display copy."""
    from sm_images.pipeline import registry
    from sm_images.pipeline.config import validate_pipeline_config

    cfg = validate_pipeline_config(collection.pipeline_config, strict=False)
    return [
        sid
        for sid in cfg.enabled()
        if (impl := registry.get_step(sid)) is not None and impl.mutates_display
    ]


async def _unsettled(db: Any, collection: Collection, image: Image) -> bool:
    mutators = _mutators(collection)
    if not mutators:
        return False
    stmt = select(StepRun.step).where(
        StepRun.image_id == image.id, StepRun.step.in_(mutators), StepRun.status.in_(_SETTLED)
    )
    settled = set((await db.execute(stmt)).scalars().all())
    return any(sid not in settled for sid in mutators)


async def resolve(
    db: Any, collection: Collection, image_id: uuid.UUID, route: str, size: str | None
) -> tuple[Image, Target]:
    loaded = await _load(db, collection, image_id, size if route == cache.RENDITION else None)
    if loaded is None:
        raise _missing()
    image, rendition_key = loaded
    if route == cache.RENDITION:
        if rendition_key is None:
            raise _missing()
        return image, Target(rendition_key, constants.DISPLAY_CONTENT_TYPE, False)
    protected = image.display_key is not None or await _unsettled(db, collection, image)
    if route == cache.DISPLAY:
        if image.display_key is not None:
            return image, Target(image.display_key, constants.DISPLAY_CONTENT_TYPE, False)
        if protected:
            raise _missing()
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
    try:
        if wanted is None:
            body = await store.stream(target.key)
        else:
            body = await store.stream_range(target.key, wanted.start, wanted.end)
    except StorageNotFoundError:
        raise _missing() from None
    status, length = 200, size
    if wanted is not None:
        status, length = 206, wanted.length
        headers["Content-Range"] = f"bytes {wanted.start}-{wanted.end}/{size}"
    headers["Content-Length"] = str(length)
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
    policy = cache.cache_headers(request, collection, route, twin=twin, protected=target.protected)
    ranged = route != cache.RENDITION
    return await _respond(request, store_for(request.app), target, policy, ranged)
