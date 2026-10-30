"""``/api/images/collections``: CRUD, visibility and the cursor list.

The parent router binds the tenant and checks CSRF. Every ``{collection_id}``
route loads its row through the access policy (``CollectionView`` and friends),
so a collection the caller may not see is a 404, and an API token is refused
(those dependencies name no ``permission=``; a route admits tokens by opting
in with its own ``RequiresResource``).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from simple_module_core.resources import ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import resource_principal

from sm_images.core import constants, events
from sm_images.core.access import CollectionEdit, CollectionOwner, CollectionView
from sm_images.ingest.imports.cleanup import cancel_for_collection
from sm_images.jobs.regroup.control import cancel_for_collection as cancel_regroups
from sm_images.models import Collection
from sm_images.web.endpoints.deps import require_create, require_view
from sm_images.web.schemas.collection import (
    CollectionCreate,
    CollectionOut,
    CollectionPageOut,
    CollectionUpdate,
    VisibilityUpdate,
)
from sm_images.web.services import collections as service
from sm_images.web.services.viewer_stats import collection_outs

router = APIRouter(prefix="/collections", tags=["collections"])

Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]
Filter = Literal["owned", "shared", "internal", "public", "all"]


def _bus(request: Request) -> object:
    return getattr(getattr(request.app.state, "sm", None), "event_bus", None)


async def out(db, row: Collection, who: ResourcePrincipal) -> CollectionOut:
    return (await collection_outs(db, who, [row]))[0]


@router.get("", dependencies=[require_view])
async def list_collections(
    who: Principal,
    db=Depends(get_db),
    filter: Filter = "all",
    limit: int = Query(constants.PAGE_DEFAULT, ge=1, le=constants.PAGE_MAX),
    cursor: str | None = Query(None, max_length=200),
) -> CollectionPageOut:
    rows, token, total = await service.list_page(
        db, who, filter_=filter, limit=limit, cursor=cursor
    )
    return CollectionPageOut(
        items=await collection_outs(db, who, rows), next_cursor=token, total=total
    )


@router.post("", status_code=201, dependencies=[require_create])
async def create_collection(
    body: CollectionCreate, who: Principal, db=Depends(get_db)
) -> CollectionOut:
    row = await service.create(
        db,
        who,
        name=body.name,
        description=body.description,
        slug=body.slug,
        visibility=body.visibility,
    )
    return await out(db, row, who)


@router.get("/{collection_id}", dependencies=[require_view])
async def get_collection(
    collection: CollectionView, who: Principal, db=Depends(get_db)
) -> CollectionOut:
    return await out(db, collection, who)


@router.patch("/{collection_id}", dependencies=[require_view])
async def update_collection(
    body: CollectionUpdate, collection: CollectionEdit, who: Principal, db=Depends(get_db)
) -> CollectionOut:
    service.update(collection, body.model_dump(exclude_unset=True))
    return await out(db, collection, who)


@router.put("/{collection_id}/visibility", dependencies=[require_view])
async def set_visibility(
    body: VisibilityUpdate,
    request: Request,
    collection: CollectionOwner,
    who: Principal,
    db=Depends(get_db),
) -> CollectionOut:
    before = await service.set_visibility(db, collection, who, body.visibility)
    if before is not collection.visibility:  # the map was withdrawn with it
        events.emit(db, _bus(request), events.visibility_changed(collection, before.value))
    return await out(db, collection, who)


@router.delete("/{collection_id}", status_code=204, dependencies=[require_view])
async def delete_collection(
    request: Request, collection: CollectionOwner, db=Depends(get_db)
) -> Response:
    events.emit(db, _bus(request), events.deleted(collection))
    # Same transaction as the trash: no import or regroup keeps writing into it.
    await cancel_for_collection(db, collection.tenant_id, collection.id)
    await cancel_regroups(db, collection.tenant_id, collection.id)
    await db.delete(collection)
    return Response(status_code=204)
