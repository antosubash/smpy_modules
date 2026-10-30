"""Groups: the photos of one site, with roles (the portal's "bags").

Reading is a ``view`` on the collection, changing is an ``edit`` (owner, an edit
share, ``images.manage``). A group is reachable exactly when its collection is,
so a stranger gets the 404 an unknown id gets. Which image is in which group,
and in which role, is set through ``PATCH /images/{id}``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from simple_module_core.resources import ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import resource_principal
from sqlalchemy import select

from sm_images import constants
from sm_images.access import (
    CollectionEdit,
    CollectionView,
    GroupCollectionView,
    RegroupCollectionEdit,
)
from sm_images.access.write import GroupCollectionEdit
from sm_images.endpoints.api._runtime import runtime, tenant
from sm_images.endpoints.deps import require_view
from sm_images.imports.access import basis
from sm_images.models import Collection, Group, RegroupJob
from sm_images.regroup import jobs
from sm_images.schemas.group import (
    GroupCreate,
    GroupOut,
    GroupPageOut,
    GroupUpdate,
    RegroupIn,
    RegroupJobOut,
    RegroupOut,
    RegroupStarted,
)
from sm_images.services import groups as service
from sm_images.services import present
from sm_images.services import regroup as regrouping
from sm_images.services.viewer_stats import viewer_only

router = APIRouter(tags=["groups"])
Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]


async def _out(
    db, collection: Collection, rows: list[Group], per_group: int, *, gated: bool = False
) -> list[GroupOut]:
    """``gated``: a viewer, who counts and sees only the display-safe members."""
    counts = await service.counts(db, rows, gate=collection if gated else None)
    found = await service.members(db, collection, [g.id for g in rows], per_group, gated=gated)
    # One rendition query for the whole page's members, not one per group.
    flat = [image for g in rows for image in found.get(g.id, [])]
    shown = dict(
        zip((i.id for i in flat), await present.present(db, collection, flat), strict=True)
    )
    return [
        GroupOut(
            id=g.id,
            collection_id=g.collection_id,
            key=g.key,
            name=g.name,
            description=g.description,
            image_count=counts.get(g.id, 0),
            members=[shown[i.id] for i in found.get(g.id, [])],
        )
        for g in rows
    ]


@router.get("/collections/{collection_id}/groups", dependencies=[require_view])
async def list_groups(
    collection: CollectionView,
    who: Principal,
    db=Depends(get_db),
    limit: int = Query(constants.PAGE_DEFAULT, ge=1, le=constants.PAGE_MAX),
    after: str | None = Query(None, max_length=constants.GROUP_KEY_MAX),
) -> GroupPageOut:
    gated = await viewer_only(db, who, collection)
    rows, token = await service.list_page(db, collection, limit=limit, after=after, gated=gated)
    items = await _out(db, collection, rows, constants.GROUP_PREVIEW_MEMBERS, gated=gated)
    return GroupPageOut(items=items, next_cursor=token)


@router.post("/collections/{collection_id}/groups", status_code=201, dependencies=[require_view])
async def create_group(
    body: GroupCreate, collection: CollectionEdit, db=Depends(get_db)
) -> GroupOut:
    row = await service.create(
        db, collection, key=body.key, name=body.name, description=body.description
    )
    return (await _out(db, collection, [row], constants.GROUP_PREVIEW_MEMBERS))[0]


def _result(done: regrouping.RegroupResult) -> RegroupOut:
    return RegroupOut(dry_run=done.dry_run, **vars(done.tally))


@router.post("/collections/{collection_id}/regroup", dependencies=[require_view])
async def regroup(
    body: RegroupIn,
    collection: CollectionEdit,
    who: Principal,
    response: Response,
    db=Depends(get_db),
) -> RegroupOut | RegroupStarted:
    """A small collection is regrouped (or previewed) now and answered with the
    counts; a big one becomes a background job: 202 and its id, polled at
    ``GET /regroups/{id}`` (one unfinished job per collection, else 409)."""
    if await regrouping.count_images(db, collection.id) <= constants.REGROUP_SYNC_MAX:
        done = await regrouping.regroup_now(
            db,
            tenant(),
            collection,
            body.pattern,
            reassign=body.reassign,
            dry_run=body.dry_run,
        )
        return _result(done)
    regrouping.compile_or_422(body.pattern)
    job_id = await jobs.create(
        runtime(),
        tenant(),
        collection.id,
        pattern=body.pattern,
        reassign=body.reassign,
        dry_run=body.dry_run,
        run_as=who.user_id,
        access_basis=await basis(db, who, collection),
    )
    await jobs.launch(runtime(), tenant(), job_id, 0)
    response.status_code = 202
    return RegroupStarted(job_id=job_id)


async def _job_out(db, job_id: uuid.UUID) -> RegroupJobOut:
    row = (await db.execute(select(RegroupJob).where(RegroupJob.id == job_id))).scalar_one()
    counters = {name: getattr(row, name) for name in vars(regrouping.Tally())}
    return RegroupJobOut(
        id=row.id,
        collection_id=row.collection_id,
        status=row.status,
        error_code=row.error_code,
        pattern=row.pattern,
        reassign=row.reassign,
        dry_run=row.dry_run,
        created_at=row.created_at,
        finished_at=row.finished_at,
        **counters,
    )


@router.get("/regroups/{regroup_id}", dependencies=[require_view])
async def get_regroup(
    regroup_id: uuid.UUID, collection: RegroupCollectionEdit, db=Depends(get_db)
) -> RegroupJobOut:
    return await _job_out(db, regroup_id)


@router.post("/regroups/{regroup_id}/cancel", dependencies=[require_view])
async def cancel_regroup(
    regroup_id: uuid.UUID, collection: RegroupCollectionEdit, db=Depends(get_db)
) -> RegroupJobOut:
    """Stop a running regroup. What it already committed stays; a finished job is unchanged."""
    await jobs.cancel(runtime(), tenant(), regroup_id)
    await db.rollback()  # re-read: the cancel committed in its own session
    return await _job_out(db, regroup_id)


@router.get("/groups/{group_id}", dependencies=[require_view])
async def get_group(
    group_id: uuid.UUID, collection: GroupCollectionView, who: Principal, db=Depends(get_db)
) -> GroupOut:
    gated = await viewer_only(db, who, collection)
    row = await service.get(db, collection, group_id, gated=gated)
    return (await _out(db, collection, [row], constants.GROUP_DETAIL_MEMBERS, gated=gated))[0]


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
