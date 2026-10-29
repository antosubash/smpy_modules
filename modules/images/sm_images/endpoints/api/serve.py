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
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from simple_module_core.resources import ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import resource_principal

from sm_images import cache, serving
from sm_images.access import ImageCollectionView
from sm_images.deps import require_view
from sm_images.endpoints.map_params import Size, get_and_head

router = APIRouter(tags=["images"])


Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]


@get_and_head(router, "/images/{image_id}/r/{size}", dependencies=[require_view])
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


@get_and_head(router, "/images/{image_id}/display", dependencies=[require_view])
async def display(
    request: Request,
    image_id: uuid.UUID,
    collection: ImageCollectionView,
    who: Principal,
    db: Any = Depends(get_db),
) -> Response:
    return await serving.serve(request, db, collection, image_id, who, cache.DISPLAY, twin=False)


@get_and_head(router, "/images/{image_id}/original", dependencies=[require_view])
async def original(
    request: Request,
    image_id: uuid.UUID,
    collection: ImageCollectionView,
    who: Principal,
    db: Any = Depends(get_db),
) -> Response:
    return await serving.serve(request, db, collection, image_id, who, cache.ORIGINAL, twin=False)
