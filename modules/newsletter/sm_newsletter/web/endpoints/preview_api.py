"""Server-rendered previews: the saved draft (view) and unsaved content (edit).

Both render with no recipient and the test unsubscribe link (R1). The saved
draft goes through ``require_campaign`` with the caller's roles (ruling C4).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sm_records.contracts.newsletter import caller_roles
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.access import require_campaign
from sm_newsletter.content.blocks import parse_body
from sm_newsletter.content.context import render_context, test_unsubscribe_url
from sm_newsletter.content.render import RenderInput, personalise, render
from sm_newsletter.core import constants
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.web.schemas.campaigns import parse_payload
from sm_newsletter.web.schemas.preview import PreviewIn, PreviewOut

router = APIRouter(dependencies=[Depends(bind_admin)])


async def _preview(
    request: Request, *, tenant: str, subject: str, preheader: str, body: object
) -> PreviewOut:
    blocks = parse_body(body)
    ctx = await render_context(request.app, tenant_id=tenant)
    template = render(RenderInput(subject=subject, preheader=preheader, blocks=blocks), ctx)
    email = personalise(
        template, first_name=None, unsubscribe_url=test_unsubscribe_url(ctx.public_base)
    )
    return PreviewOut(
        subject=email.subject, html=email.html, text=email.text, warnings=list(template.warnings)
    )


@router.get(
    "/campaigns/{campaign_id}/preview",
    response_model=PreviewOut,
    dependencies=[Depends(RequiresPermission(constants.PERM_VIEW))],
)
async def preview_saved(
    campaign_id: int,
    request: Request,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> PreviewOut:
    campaign = await require_campaign(
        db, tenant_id=tenant, campaign_id=campaign_id, roles=caller_roles(request)
    )
    return await _preview(
        request,
        tenant=tenant,
        subject=campaign.subject,
        preheader=campaign.preheader,
        body=campaign.body,
    )


@router.post(
    "/preview",
    response_model=PreviewOut,
    dependencies=[Depends(RequiresPermission(constants.PERM_EDIT))],
)
async def preview_unsaved(
    request: Request, payload: Any = Body(...), tenant: str = Depends(bind_admin)
) -> PreviewOut:
    data = parse_payload(PreviewIn, payload)
    return await _preview(
        request, tenant=tenant, subject=data.subject, preheader=data.preheader, body=data.body
    )
