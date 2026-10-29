"""Groups: the photos of one site, with roles (the portal's "bags").

Reading is a ``view`` on the collection, changing is an ``edit`` (owner, an edit
share, ``images.manage``). A group is reachable exactly when its collection is,
so a stranger gets the 404 an unknown id gets. Which image is in which group,
and in which role, is set through ``PATCH /images/{id}``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response
from simple_module_db.deps import get_db

from sm_images import constants
from sm_images.access import (
    CollectionEdit,
    CollectionView,
    GroupCollectionEdit,
    GroupCollectionView,
)
from sm_images.deps import require_view
from sm_images.models import Collection, Group
from sm_images.schemas.group import (
    GroupCreate,
    GroupOut,
    GroupPageOut,
    GroupUpdate,
    RegroupIn,
    RegroupOut,
)
from sm_images.services import groups as service
from sm_images.services import present
from sm_images.services import regroup as regrouping

router = APIRouter(tags=["groups"])


async def _out(db, collection: Collection, rows: list[Group], per_group: int) -> list[GroupOut]:
    counts = await service.counts(db, rows)
    found = await service.members(db, collection, [g.id for g in rows], per_group)
    return [
        GroupOut(
            id=g.id,
            collection_id=g.collection_id,
            key=g.key,
            name=g.name,
            description=g.description,
            image_count=counts.get(g.id, 0),
            members=await present.present(db, collection, found.get(g.id, [])),
        )
        for g in rows
    ]


@router.get("/collections/{collection_id}/groups", dependencies=[require_view])
async def list_groups(
    collection: CollectionView,
    db=Depends(get_db),
    limit: int = Query(constants.PAGE_DEFAULT, ge=1, le=constants.PAGE_MAX),
    after: str | None = Query(None, max_length=constants.GROUP_KEY_MAX),
) -> GroupPageOut:
    rows, token = await service.list_page(db, collection, limit=limit, after=after)
    items = await _out(db, collection, rows, constants.GROUP_PREVIEW_MEMBERS)
    return GroupPageOut(items=items, next_cursor=token)


@router.post("/collections/{collection_id}/groups", status_code=201, dependencies=[require_view])
async def create_group(
    body: GroupCreate, collection: CollectionEdit, db=Depends(get_db)
) -> GroupOut:
    row = await service.create(
        db, collection, key=body.key, name=body.name, description=body.description
    )
    return (await _out(db, collection, [row], constants.GROUP_PREVIEW_MEMBERS))[0]


@router.post("/collections/{collection_id}/regroup", dependencies=[require_view])
async def regroup(body: RegroupIn, collection: CollectionEdit, db=Depends(get_db)) -> RegroupOut:
    return await regrouping.regroup(
        db, collection, body.pattern, reassign=body.reassign, dry_run=body.dry_run
    )


@router.get("/groups/{group_id}", dependencies=[require_view])
async def get_group(
    group_id: uuid.UUID, collection: GroupCollectionView, db=Depends(get_db)
) -> GroupOut:
    row = await service.get(db, collection, group_id)
    return (await _out(db, collection, [row], constants.GROUP_DETAIL_MEMBERS))[0]


@router.patch("/groups/{group_id}", dependencies=[require_view])
async def patch_group(
    group_id: uuid.UUID, body: GroupUpdate, collection: GroupCollectionEdit, db=Depends(get_db)
) -> GroupOut:
    row = await service.get(db, collection, group_id)
    row = await service.update_group(db, collection, row, body.model_dump(exclude_unset=True))
    return (await _out(db, collection, [row], constants.GROUP_DETAIL_MEMBERS))[0]


@router.delete("/groups/{group_id}", status_code=204, dependencies=[require_view])
async def delete_group(
    group_id: uuid.UUID, collection: GroupCollectionEdit, db=Depends(get_db)
) -> Response:
    await service.delete_group(db, collection, await service.get(db, collection, group_id))
    return Response(status_code=204)
