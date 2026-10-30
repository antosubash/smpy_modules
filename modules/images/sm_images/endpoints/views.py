"""Inertia screens of the Images module, mounted under ``VIEW_PREFIX``.

Screens only *read* through Inertia; writes go through the JSON API with
``fetch()``. The gallery itself is fetched by the page (cursor and filters), so
a screen carries the collection and what the caller may do with it - never the
images. Route order: ``/images/{id}`` has two segments and ``/{collection_id}``
one, so neither can swallow the other.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from simple_module_core.resources import ACTION_DELETE, ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_hosting.resource_deps import resource_principal
from simple_module_inertia import InertiaResponse

from sm_images.access import (
    POLICY,
    CollectionEdit,
    CollectionView,
    ImageCollectionView,
    can_edit,
    can_view_original,
)
from sm_images.access import redaction as redaction_state
from sm_images.core import constants
from sm_images.endpoints.csrf import share_csrf_token
from sm_images.endpoints.deps import get_settings, require_view
from sm_images.schemas.collection import CollectionOut, CollectionPageOut
from sm_images.services import collections as collection_service
from sm_images.services import gallery, present
from sm_images.services.neighbors import neighbors
from sm_images.services.viewer_stats import collection_outs, viewer_only
from sm_images.tenancy import bind_admin

# ``bind_admin`` first, for the reason ``endpoints.api``'s router gives.
router = APIRouter(dependencies=[Depends(bind_admin), require_view, Depends(share_csrf_token)])

Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]


async def _out(db: Any, row: Any, who: ResourcePrincipal) -> CollectionOut:
    return (await collection_outs(db, who, [row]))[0]


async def _rights(db: Any, who: ResourcePrincipal, collection: Any) -> dict[str, bool]:
    # Delete and share are never granted by a share, so the in-memory ``can`` is
    # exact; edit can come from a share row, so it asks the database.
    owner = POLICY.can(who, ACTION_DELETE, collection)
    return {
        "can_edit": await can_edit(db, who, collection),
        "can_manage": owner,
        "can_share": owner and who.has(constants.PERM_SHARE),
        "can_publish": who.has(constants.PERM_PUBLISH),
    }


@router.get("/", response_model=None)
async def collections(
    inertia: InertiaDep, who: Principal, db: Any = Depends(get_db)
) -> InertiaResponse:
    rows, token, total = await collection_service.list_page(db, who)
    page = CollectionPageOut(
        items=await collection_outs(db, who, rows), next_cursor=token, total=total
    )
    return await inertia.render(
        constants.PAGE_COLLECTIONS,
        {
            "collections": page.model_dump(mode="json"),
            "can_create": who.has(constants.PERM_CREATE),
            "can_publish": who.has(constants.PERM_PUBLISH),
        },
    )


@router.get("/images/{image_id}", response_model=None)
async def image(
    image_id: uuid.UUID,
    inertia: InertiaDep,
    collection: ImageCollectionView,
    who: Principal,
    db: Any = Depends(get_db),
) -> InertiaResponse:
    """The viewer. ``can_view_original`` is the serving route's own rule, fed the
    same protection state (a display copy, or a display mutator that has not
    settled), so the toggle is offered exactly when ``/original`` would answer
    200. ``display_pending`` is when ``…/display`` would 404 (redaction has not
    settled), so the page says so instead of showing a broken picture."""
    gated = await viewer_only(db, who, collection)
    row = await gallery.get(db, collection, image_id, gated=gated)
    withheld = not redaction_state.trusts_display(
        collection, row
    ) and await redaction_state.pending(db, collection, row)
    protected = row.display_key is not None or withheld
    rights = await _rights(db, who, collection)
    return await inertia.render(
        constants.PAGE_IMAGE,
        {
            "image": (await present.present_detail(db, collection, row, who)).model_dump(
                mode="json"
            ),
            "collection": (await _out(db, collection, who)).model_dump(mode="json"),
            "can_view_original": can_view_original(who, row, collection, protected=protected),
            "display_pending": withheld,
            "group_roles": list(collection.group_roles or []),
            # Previous / next in gallery order, among the images this caller may open.
            "neighbors": await neighbors(db, collection, row, gated=gated),
            "can_edit": rights["can_edit"],
            "can_manage": rights["can_manage"],
        },
    )


@router.get("/{collection_id}", response_model=None)
async def collection_page(
    request: Request,
    collection: CollectionView,
    inertia: InertiaDep,
    who: Principal,
    db: Any = Depends(get_db),
) -> InertiaResponse:
    return await inertia.render(
        constants.PAGE_COLLECTION,
        {
            "collection": (await _out(db, collection, who)).model_dump(mode="json"),
            **await _rights(db, who, collection),
            # Where the uploader switches from one multipart request to a direct upload.
            "direct_upload_threshold": get_settings(request).direct_upload_threshold,
            # The basemap the Map tab draws under the points; empty is a flat background.
            "map_style_url": get_settings(request).map_style_url,
            # Linked (and copyable) on the page while the collection is public.
            "public_path": f"{constants.PUBLIC_COLLECTION_PREFIX}{collection.slug}",
        },
    )


@router.get("/{collection_id}/review", response_model=None)
async def review_page(
    collection: CollectionEdit, inertia: InertiaDep, who: Principal, db: Any = Depends(get_db)
) -> InertiaResponse:
    """The review queue; the results themselves are fetched by the page."""
    return await inertia.render(
        constants.PAGE_REVIEW,
        {"collection": (await _out(db, collection, who)).model_dump(mode="json")},
    )
