"""``/campaigns`` (draft CRUD) and ``/lists`` (the lists a campaign can go to).

``bind_admin`` first on the router (see ``settings_api``), each route's
permission after it; the CSRF check wraps the whole API in ``module.py``.
Bodies arrive as raw JSON and are validated by ``parse_payload``, so a 422
never echoes the submitted value. The caller's roles (records' list
narrowing) come from ``sm_records.contracts.newsletter.caller_roles``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sm_records.contracts.newsletter import caller_roles
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns import access, drafts
from sm_newsletter.core import constants
from sm_newsletter.core.errors import InvalidCampaign
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.web.schemas.campaigns import (
    CampaignCreate,
    CampaignDetail,
    CampaignPage,
    CampaignPatch,
    CampaignSummary,
    parse_payload,
)

router = APIRouter(dependencies=[Depends(bind_admin)])

_VIEW = [Depends(RequiresPermission(constants.PERM_VIEW))]
_EDIT = [Depends(RequiresPermission(constants.PERM_EDIT))]


@router.get("/campaigns", response_model=CampaignPage, dependencies=_VIEW)
async def list_campaigns(
    request: Request,
    tenant: str = Depends(bind_admin),
    status: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=drafts.MAX_PAGE),
    db: AsyncSession = Depends(get_db),
) -> CampaignPage:
    # Checked here, not by FastAPI, whose 422 would echo the value back.
    if status is not None and status not in constants.CAMPAIGN_STATUSES:
        raise InvalidCampaign("status: invalid value")
    items, total = await drafts.list_campaigns(
        db,
        tenant_id=tenant,
        roles=caller_roles(request),
        status=status,
        q=q,
        offset=offset,
        limit=limit,
    )
    return CampaignPage(items=[CampaignSummary.model_validate(c) for c in items], total=total)


@router.post("/campaigns", response_model=CampaignDetail, status_code=201, dependencies=_EDIT)
async def create_campaign(
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> CampaignDetail:
    data = parse_payload(CampaignCreate, payload)
    campaign = await drafts.create_draft(
        db, tenant_id=tenant, data=data, roles=caller_roles(request)
    )
    return CampaignDetail.model_validate(campaign)


@router.get("/campaigns/{campaign_id}", response_model=CampaignDetail, dependencies=_VIEW)
async def get_campaign(
    campaign_id: int,
    request: Request,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> CampaignDetail:
    campaign = await drafts.get_campaign(
        db, tenant_id=tenant, campaign_id=campaign_id, roles=caller_roles(request)
    )
    return CampaignDetail.model_validate(campaign)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignDetail, dependencies=_EDIT)
async def patch_campaign(
    campaign_id: int,
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> CampaignDetail:
    patch = parse_payload(CampaignPatch, payload)
    campaign = await drafts.update_draft(
        db, tenant_id=tenant, campaign_id=campaign_id, patch=patch, roles=caller_roles(request)
    )
    return CampaignDetail.model_validate(campaign)


@router.delete("/campaigns/{campaign_id}", status_code=204, dependencies=_EDIT)
async def delete_campaign(
    campaign_id: int,
    request: Request,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await drafts.delete_draft(
        db, tenant_id=tenant, campaign_id=campaign_id, roles=caller_roles(request)
    )
    return Response(status_code=204)


@router.get("/lists", response_model=list[str], dependencies=_VIEW)
async def lists(
    request: Request, tenant: str = Depends(bind_admin), db: AsyncSession = Depends(get_db)
) -> list[str]:
    return await access.readable_lists(db, tenant_id=tenant, roles=caller_roles(request))
