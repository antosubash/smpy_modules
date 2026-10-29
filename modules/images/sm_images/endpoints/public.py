"""The anonymous twins of the byte and map routes, under ``/api/images/public/`` (spec §5).

``/public/c/{slug}/images/{image_id}/r/{size}``, ``…/display``,
``…/original``, ``/public/c/{slug}/points`` and ``…/map.pmtiles`` (``GET``
and ``HEAD`` only): a **public** collection's images and map for anyone, through
``bind_public`` and :func:`~sm_images.access.public_collection`. A private or
internal collection is the 404 an unknown slug gets, whoever asks - the owner
included, who has the admin routes.

The twin answers as the anonymous surface for everyone: the caller's identity
is never consulted, so a protected original is a 403 here even for its owner,
and the answer is the same for every reader - which is what lets
``sm_images.cache`` make a rendition or display copy shareable here (and only
here, and only when no request-specific source picked the tenant).

Error answers carry ``Cache-Control: no-store``: the same URL can be a 200 for
one tenant and a 404 for another, and a cache may keep a 404 heuristically
when nothing forbids it (records' review m1).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.routing import APIRoute
from simple_module_core.resources import ResourcePrincipal
from simple_module_db.deps import get_db

from sm_images import cache, constants, serving
from sm_images.access import public_collection
from sm_images.endpoints.map_params import BBox, Cursor, Limit, points_response
from sm_images.errors import ImagesError, render
from sm_images.models import Collection
from sm_images.services import public_gallery
from sm_images.tenancy import bind_public

_NO_STORE = "no-store"
ANONYMOUS = ResourcePrincipal(user_id=None)


class PublicRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            try:
                return await handler(request)
            except ImagesError as exc:
                response = await render(request, exc)
                response.headers["Cache-Control"] = _NO_STORE
                return response

        return wrapped


router = APIRouter(
    prefix=constants.PUBLIC_API_ROUTER_PREFIX,
    tags=["images-public"],
    dependencies=[Depends(bind_public)],
    route_class=PublicRoute,
)


def _get_and_head(path: str, **kw: Any) -> Callable[[Any], Any]:
    """``GET`` plus ``HEAD`` (same access and cache path, no body). ``HEAD`` is
    kept out of the OpenAPI document, where it would duplicate the operation."""

    def register(endpoint: Any) -> Any:
        router.head(path, include_in_schema=False, response_model=None, **kw)(endpoint)
        return router.get(path, response_model=None, **kw)(endpoint)

    return register


Public = Annotated[Collection, Depends(public_collection)]
Size = Annotated[str, Path(max_length=constants.RENDITION_SIZE_MAX)]
_BASE = "/c/{slug}/images/{image_id}"


@_get_and_head(f"{_BASE}/r/{{size}}")
async def public_rendition(
    request: Request, image_id: uuid.UUID, size: Size, collection: Public, db: Any = Depends(get_db)
) -> Response:
    return await serving.serve(
        request, db, collection, image_id, ANONYMOUS, cache.RENDITION, size=size, twin=True
    )


@_get_and_head(f"{_BASE}/display")
async def public_display(
    request: Request, image_id: uuid.UUID, collection: Public, db: Any = Depends(get_db)
) -> Response:
    return await serving.serve(
        request, db, collection, image_id, ANONYMOUS, cache.DISPLAY, twin=True
    )


@_get_and_head(f"{_BASE}/original")
async def public_original(
    request: Request, image_id: uuid.UUID, collection: Public, db: Any = Depends(get_db)
) -> Response:
    return await serving.serve(
        request, db, collection, image_id, ANONYMOUS, cache.ORIGINAL, twin=True
    )


@router.get("/c/{slug}/images")
async def public_images(
    request: Request,
    response: Response,
    collection: Public,
    db: Any = Depends(get_db),
    limit: int = Query(constants.PAGE_DEFAULT, ge=1, le=constants.PAGE_MAX),
    cursor: str | None = Query(None, max_length=200),
) -> dict[str, Any]:
    """The gallery of a public collection: ids, sizes and anonymous URLs, never a
    filename or metadata. Only images whose ``small`` rendition may be shown."""
    body = await public_gallery.page(db, collection, limit=limit, cursor=cursor)
    response.headers["Cache-Control"] = cache.cache_headers(
        request, collection, cache.DISPLAY, twin=True
    )
    return body


@router.get("/c/{slug}/points")
async def public_points(
    request: Request,
    response: Response,
    collection: Public,
    db: Any = Depends(get_db),
    bbox: str | None = BBox,
    limit: int = Limit,
    cursor: str | None = Cursor,
) -> dict[str, Any]:
    return await points_response(
        request, response, db, collection, bbox=bbox, limit=limit, cursor=cursor, twin=True
    )


@_get_and_head("/c/{slug}/map.pmtiles")
async def public_map(request: Request, collection: Public) -> Response:
    """Re-checked as public on every request, every range of a viewer included:
    a collection made private stops here at once (and its archive was withdrawn
    with the change, ``sm_images.map.revoke.withdraw``)."""
    return await serving.serve_map(request, collection, twin=True)
