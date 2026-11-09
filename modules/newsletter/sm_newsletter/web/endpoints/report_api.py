"""``GET /campaigns/{id}/report``: counters, per-link clicks and the timeline.

``bind_admin`` first, then the permission; the campaign is read through
``require_campaign`` with the caller's roles (C4), so a list narrowed past the
caller answers 404.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sm_records.contracts.newsletter import caller_roles
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.access import require_campaign
from sm_newsletter.core import constants
from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.tracking.report import campaign_report
from sm_newsletter.web.schemas.report import ReportOut

router = APIRouter(dependencies=[Depends(bind_admin)])


@router.get(
    "/campaigns/{campaign_id}/report",
    response_model=ReportOut,
    dependencies=[Depends(RequiresPermission(constants.PERM_VIEW))],
)
async def report(
    campaign_id: int,
    request: Request,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> ReportOut:
    campaign = await require_campaign(
        db, tenant_id=tenant, campaign_id=campaign_id, roles=caller_roles(request)
    )
    settings = getattr(request.app.state, constants.PACKAGE).settings
    result = await campaign_report(db, settings, tenant_id=tenant, campaign=campaign, now=utcnow())
    return ReportOut.model_validate(result, from_attributes=True)
