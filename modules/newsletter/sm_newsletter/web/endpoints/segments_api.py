"""``/segments``: saved segments and their live count.

``bind_admin`` first on the router, each route's permission after it. Bodies
arrive raw and go through ``parse_payload`` (error ``invalid_segment``), so a
422 never echoes a rule value.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sm_records.contracts.newsletter import caller_roles
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import constants
from sm_newsletter.core.errors_audience import InvalidSegment
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.segments import store
from sm_newsletter.web.schemas.campaigns import parse_payload
from sm_newsletter.web.schemas.segments import (
    CountOut,
    SegmentCreate,
    SegmentOut,
    SegmentPatch,
    SegmentPreviewIn,
)

router = APIRouter(dependencies=[Depends(bind_admin)])

_VIEW = [Depends(RequiresPermission(constants.PERM_VIEW))]
_EDIT = [Depends(RequiresPermission(constants.PERM_EDIT))]


@router.get("/segments", response_model=list[SegmentOut], dependencies=_VIEW)
async def list_segments(
    request: Request,
    tenant: str = Depends(bind_admin),
    list_type_key: str | None = Query(None, max_length=constants.MAX_TYPE_KEY_LEN),
    db: AsyncSession = Depends(get_db),
) -> list[SegmentOut]:
    rows = await store.list_segments(
        db, tenant_id=tenant, roles=caller_roles(request), list_type_key=list_type_key
    )
    return [SegmentOut.model_validate(r) for r in rows]


@router.post("/segments", response_model=SegmentOut, status_code=201, dependencies=_EDIT)
async def create_segment(
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> SegmentOut:
    data = parse_payload(SegmentCreate, payload, error=InvalidSegment)
    segment = await store.create_segment(
        db,
        tenant_id=tenant,
        roles=caller_roles(request),
        name=data.name,
        list_type_key=data.list_type_key,
        rules=data.rules,
    )
    return SegmentOut.model_validate(segment)


@router.post("/segments/preview", response_model=CountOut, dependencies=_VIEW)
async def preview_segment(
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> CountOut:
    data = parse_payload(SegmentPreviewIn, payload, error=InvalidSegment)
    count = await store.preview(
        db,
        tenant_id=tenant,
        roles=caller_roles(request),
        list_type_key=data.list_type_key,
        rules=data.rules,
    )
    return CountOut(count=count)


@router.get("/segments/{segment_id}", response_model=SegmentOut, dependencies=_VIEW)
async def get_segment(
    segment_id: int,
    request: Request,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> SegmentOut:
    segment = await store.get_segment(
        db, tenant_id=tenant, segment_id=segment_id, roles=caller_roles(request)
    )
    return SegmentOut.model_validate(segment)


@router.patch("/segments/{segment_id}", response_model=SegmentOut, dependencies=_EDIT)
async def patch_segment(
    segment_id: int,
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> SegmentOut:
    data = parse_payload(SegmentPatch, payload, error=InvalidSegment)
    segment = await store.update_segment(
        db,
        tenant_id=tenant,
        segment_id=segment_id,
        roles=caller_roles(request),
        name=data.name,
        rules=data.rules,
    )
    return SegmentOut.model_validate(segment)


@router.delete("/segments/{segment_id}", status_code=204, dependencies=_EDIT)
async def delete_segment(
    segment_id: int,
    request: Request,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await store.delete_segment(
        db, tenant_id=tenant, segment_id=segment_id, roles=caller_roles(request)
    )
    return Response(status_code=204)
