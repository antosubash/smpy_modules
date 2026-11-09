"""``/campaigns/{id}/send`` and friends: the sending lifecycle, its progress and estimate.

``bind_admin`` first on the router, each route's permission after it; the CSRF
check wraps the whole API in ``module.py`` and ``get_db`` commits on success,
so a refusal leaves nothing behind. Bodies go through ``parse_payload`` (a 422
never echoes input). The caller's roles narrow the lists (ruling C4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sm_records.contracts.newsletter import caller_roles
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns import lifecycle
from sm_newsletter.campaigns.access import require_campaign
from sm_newsletter.campaigns.checks import SCHEDULE_GRACE, SCHEDULE_HORIZON
from sm_newsletter.campaigns.progress import estimate, progress
from sm_newsletter.core import constants
from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.errors import InvalidCampaign
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.web.schemas.campaigns import CampaignDetail, parse_payload
from sm_newsletter.web.schemas.sending import (
    EstimateOut,
    ProgressOut,
    RevisionIn,
    ScheduleIn,
)

router = APIRouter(dependencies=[Depends(bind_admin)])

_VIEW = [Depends(RequiresPermission(constants.PERM_VIEW))]
_SEND = [Depends(RequiresPermission(constants.PERM_SEND))]
_PATH = "/campaigns/{campaign_id}"


def _settings(request: Request) -> Any:
    return getattr(request.app.state, constants.PACKAGE).settings


def _factory(request: Request) -> Any:
    return request.app.state.sm.db.session_factory


@router.post(f"{_PATH}/send", response_model=CampaignDetail, dependencies=_SEND)
async def send(
    campaign_id: int,
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> CampaignDetail:
    data = parse_payload(ScheduleIn, payload)
    campaign = await lifecycle.schedule(
        request.app,
        db,
        tenant_id=tenant,
        campaign_id=campaign_id,
        roles=caller_roles(request),
        expected_revision=data.expected_revision,
        scheduled_at=data.scheduled_at,
        now=utcnow(),
    )
    return CampaignDetail.model_validate(campaign)


@router.post(f"{_PATH}/unschedule", response_model=CampaignDetail, dependencies=_SEND)
async def unschedule(
    campaign_id: int,
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> CampaignDetail:
    data = parse_payload(RevisionIn, payload)
    campaign = await lifecycle.unschedule(
        db,
        tenant_id=tenant,
        campaign_id=campaign_id,
        roles=caller_roles(request),
        expected_revision=data.expected_revision,
    )
    return CampaignDetail.model_validate(campaign)


def _action(name: str, act: Any) -> None:
    async def route(
        campaign_id: int,
        request: Request,
        tenant: str = Depends(bind_admin),
        db: AsyncSession = Depends(get_db),
    ) -> CampaignDetail:
        campaign = await act(
            db,
            tenant_id=tenant,
            campaign_id=campaign_id,
            roles=caller_roles(request),
            now=utcnow(),
        )
        return CampaignDetail.model_validate(campaign)

    route.__name__ = name
    router.post(f"{_PATH}/{name}", response_model=CampaignDetail, dependencies=_SEND)(route)


_action("pause", lifecycle.pause)
_action("resume", lifecycle.resume)
_action("cancel", lifecycle.cancel)


@router.get(f"{_PATH}/progress", response_model=ProgressOut, dependencies=_VIEW)
async def get_progress(
    campaign_id: int,
    request: Request,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> ProgressOut:
    campaign = await require_campaign(
        db, tenant_id=tenant, campaign_id=campaign_id, roles=caller_roles(request)
    )
    return await progress(
        db, _factory(request), _settings(request), tenant_id=tenant, campaign=campaign, now=utcnow()
    )


@router.get(f"{_PATH}/estimate", response_model=EstimateOut, dependencies=_SEND)
async def get_estimate(
    campaign_id: int,
    request: Request,
    # A string, checked here: FastAPI's own 422 would echo the value.
    at: str | None = Query(None, max_length=64),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> EstimateOut:
    start = _parse_at(at)
    campaign = await require_campaign(
        db, tenant_id=tenant, campaign_id=campaign_id, roles=caller_roles(request)
    )
    return await estimate(
        db,
        _factory(request),
        _settings(request),
        tenant_id=tenant,
        campaign=campaign,
        at=start,
    )


def _parse_at(raw: str | None) -> datetime:
    if raw is None:
        return utcnow()
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise InvalidCampaign("at: invalid value") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidCampaign("at: invalid value")
    now = utcnow()
    # The window a schedule time may fall in (ruling S19), so the sum below cannot overflow.
    if not now - SCHEDULE_GRACE <= parsed <= now + SCHEDULE_HORIZON:
        raise InvalidCampaign("at: out of range")
    return parsed
