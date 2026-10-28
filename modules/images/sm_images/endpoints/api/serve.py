"""``GET /images/{image_id}/r/{size}``, ``…/display`` and ``…/original`` (spec §5).

The access-checked byte routes of the console and API. ``ImageCollectionView``
loads the image's collection through the policy, so an image the caller may
not see is the 404 an absent id gets; everything after that - which object,
the original's own right, cache headers, 304, ``Range`` - is
:func:`sm_images.serving.serve`. Never shareable-cached: the answer depends on
who asks (``sm_images.cache``).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, Response
from simple_module_core.resources import ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import resource_principal

from sm_images import cache, constants, serving
from sm_images.access import ImageCollectionView
from sm_images.deps import require_view

router = APIRouter(tags=["images"])


def _get_and_head(path: str, **kw: Any) -> Callable[[Any], Any]:
    """``GET`` plus ``HEAD`` (same access and cache path, no body). ``HEAD`` is
    kept out of the OpenAPI document, where it would duplicate the operation."""

    def register(endpoint: Any) -> Any:
        router.head(path, include_in_schema=False, response_model=None, **kw)(endpoint)
        return router.get(path, response_model=None, **kw)(endpoint)

    return register


Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]
Size = Annotated[str, Path(max_length=constants.RENDITION_SIZE_MAX)]


@_get_and_head("/images/{image_id}/r/{size}", dependencies=[require_view])
async def rendition(
    request: Request,
    image_id: uuid.UUID,
    size: Size,
    collection: ImageCollectionView,
    who: Principal,
    db: Any = Depends(get_db),
) -> Response:
    return await serving.serve(
        request, db, collection, image_id, who, cache.RENDITION, size=size, twin=False
    )


@_get_and_head("/images/{image_id}/display", dependencies=[require_view])
async def display(
    request: Request,
    image_id: uuid.UUID,
    collection: ImageCollectionView,
    who: Principal,
    db: Any = Depends(get_db),
) -> Response:
    return await serving.serve(request, db, collection, image_id, who, cache.DISPLAY, twin=False)


@_get_and_head("/images/{image_id}/original", dependencies=[require_view])
async def original(
    request: Request,
    image_id: uuid.UUID,
    collection: ImageCollectionView,
    who: Principal,
    db: Any = Depends(get_db),
) -> Response:
    return await serving.serve(request, db, collection, image_id, who, cache.ORIGINAL, twin=False)
