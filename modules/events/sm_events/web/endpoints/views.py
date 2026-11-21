"""Tenant-bound console screens; their data is loaded from the API."""

from fastapi import APIRouter, Depends, Request
from simple_module_core.permissions import grants
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_hosting.permissions import ensure_resolved_permissions
from simple_module_inertia import InertiaResponse
from starlette.responses import RedirectResponse

from sm_events.core import constants, tenancy, timezones
from sm_events.web.endpoints.deps import get_settings, require_manage, require_view

router = APIRouter(dependencies=[Depends(tenancy.bind_admin)])


@router.get("/", dependencies=[require_view])
async def root() -> RedirectResponse:
    return RedirectResponse(constants.CALENDARS_URL, status_code=303)


@router.get("/calendars", response_model=None, dependencies=[require_view])
async def calendars_page(request: Request, inertia: InertiaDep) -> InertiaResponse:
    held = await ensure_resolved_permissions(request)
    return await inertia.render(
        constants._PAGE_CALENDARS,
        {
            **tenancy.view_props(request),
            "can_create": grants(held, constants.PERM_EDIT),
            "can_manage": grants(held, constants.PERM_MANAGE),
            "default_timezone": timezones.effective(get_settings(request).default_timezone),
            "user_id": str(request.state.user.id),
        },
    )


@router.get("/categories", response_model=None, dependencies=[require_view, require_manage])
async def categories_page(request: Request, inertia: InertiaDep) -> InertiaResponse:
    return await inertia.render(
        constants._PAGE_CATEGORIES,
        {
            **tenancy.view_props(request),
            "content_locales": list(get_settings(request).content_locales),
        },
    )
