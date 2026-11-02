"""The public collection page, ``/images/c/{slug}`` (spec §6, Public).

An Inertia screen for anyone, through ``bind_public`` and
:func:`~sm_images.core.access.public_collection`: a private or internal collection is
the 404 an unknown slug gets, whoever asks. The screen reads the gallery and map
from the anonymous twins in :mod:`sm_images.web.endpoints.public`; this route only
names the collection. Mounted at the app root by ``ImagesModule.on_startup``
(the console router is hard-prefixed with ``VIEW_PREFIX``).

The HTML carries the viewer's shared props, so it is never shareable-cached,
whichever way the tenant was chosen: the shareable rule is for the byte routes.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from simple_module_db.deps import get_db
from simple_module_hosting.inertia_deps import InertiaDep

from sm_images.core import constants
from sm_images.core.access import public_collection
from sm_images.core.tenancy import bind_public
from sm_images.models import Collection
from sm_images.web.endpoints.deps import get_settings
from sm_images.web.endpoints.public import PublicRoute
from sm_images.web.services.viewer_stats import public_fields
from sm_images.web.serving import cache

router = APIRouter(
    prefix=constants.PUBLIC_COLLECTION_PREFIX.rstrip("/"),
    tags=["images-public"],
    dependencies=[Depends(bind_public)],
    route_class=PublicRoute,
)

# Never the owner, the id or the timestamps: a visitor needs only what the page shows.
_SHOWN = ("slug", "name", "description", "image_count", "located_count", "bbox")
Public = Annotated[Collection, Depends(public_collection)]


@router.get("/{slug}", response_model=None)
async def public_collection_page(
    request: Request, collection: Public, inertia: InertiaDep, db: Any = Depends(get_db)
) -> Response:
    # Counts and box over the display-safe images only: a withheld one is not shown.
    shown = await public_fields(db, collection)
    response = await inertia.render(
        constants.PAGE_PUBLIC_COLLECTION,
        {
            "collection": {name: shown[name] for name in _SHOWN},
            # The basemap under the map; empty is a flat background.
            "map_style_url": get_settings(request).map_style_url,
        },
    )
    response.headers["Cache-Control"] = cache.PRIVATE_NO_CACHE
    return response
