"""Inertia screens: the campaign list, the editor and the settings page.

``bind_admin`` first (as in every admin router here), then the shared CSRF
token. The data is fetched client-side from ``/api/newsletter``; the props only
carry what the first paint needs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_core.permissions import grants
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_hosting.permissions import RequiresPermission, ensure_resolved_permissions
from simple_module_inertia import InertiaResponse
from sm_records.contracts.newsletter import caller_roles
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.access import require_campaign
from sm_newsletter.campaigns.test_send import MAX_TEST_RECIPIENTS
from sm_newsletter.content.integrations import capabilities
from sm_newsletter.core import constants, tenancy
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.web.endpoints.csrf import share_csrf_token

router = APIRouter(dependencies=[Depends(bind_admin), Depends(share_csrf_token)])


async def _flags(request: Request) -> dict[str, bool]:
    held = await ensure_resolved_permissions(request)
    return {
        "can_edit": grants(held, constants.PERM_EDIT),
        "can_send": grants(held, constants.PERM_SEND),
    }


@router.get(
    "/",
    response_model=None,
    dependencies=[Depends(RequiresPermission(constants.PERM_VIEW))],
)
async def campaign_list(request: Request, inertia: InertiaDep) -> InertiaResponse:
    return await inertia.render(
        constants._PAGE_CAMPAIGNS, {**tenancy.view_props(request), **await _flags(request)}
    )


@router.get(
    "/settings",
    response_model=None,
    dependencies=[Depends(RequiresPermission(constants.PERM_MANAGE))],
)
async def settings_page(request: Request, inertia: InertiaDep) -> InertiaResponse:
    held = await ensure_resolved_permissions(request)
    return await inertia.render(
        constants._PAGE_SETTINGS,
        {**tenancy.view_props(request), "can_write": grants(held, constants.PERM_SETTINGS_EDIT)},
    )


@router.get(
    "/campaigns/{campaign_id}",
    response_model=None,
    dependencies=[Depends(RequiresPermission(constants.PERM_VIEW))],
)
async def campaign_editor(
    campaign_id: int,
    request: Request,
    inertia: InertiaDep,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> InertiaResponse:
    """Only the id is rendered; the campaign is fetched client-side. The lookup
    still runs here so an unknown or unreadable campaign is a 404 page."""
    await require_campaign(
        db, tenant_id=tenant, campaign_id=campaign_id, roles=caller_roles(request)
    )
    host = getattr(request.app.state.sm, "settings", None)
    return await inertia.render(
        constants._PAGE_EDITOR,
        {
            **tenancy.view_props(request),
            "campaign_id": campaign_id,
            **await _flags(request),
            "capabilities": capabilities(request.app),
            "public_base_url_set": bool(getattr(host, "public_base_url", "") or ""),
            "max_test_recipients": MAX_TEST_RECIPIENTS,
        },
    )
