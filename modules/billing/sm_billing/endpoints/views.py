"""Tenant billing screen (``/billing/``). Reads only; mutations go through the API.

The permission is checked in the handler rather than as a route dependency:
a signed-in user with no active tenant holds no ``tenant:*`` role yet, and
should be sent to pick an organisation, not shown a 403.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from simple_module_core.permissions import grants
from simple_module_db.deps import get_db
from simple_module_hosting.csrf import get_csrf_token
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_hosting.permissions import resolved_permissions_for
from simple_module_inertia import InertiaResponse
from sqlalchemy.ext.asyncio import AsyncSession

from sm_billing import constants as c
from sm_billing.checkout import BillingService

router = APIRouter()

NO_TENANT_REDIRECT = "/tenants/?reason=tenant_required"


def _perm(request: Request, permission: str) -> bool:
    return grants(resolved_permissions_for(request), permission)


@router.get("/", response_model=None)
async def billing_page(
    request: Request, inertia: InertiaDep, db: AsyncSession = Depends(get_db)
) -> InertiaResponse | RedirectResponse:
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is None or not _perm(request, c.PERM_VIEW):
        return RedirectResponse(NO_TENANT_REDIRECT, status_code=303)
    service = BillingService(db, request.app, tenant_id)
    can_manage = _perm(request, c.PERM_MANAGE) and (
        getattr(request.state, "tenant_role", None) == c.TENANT_ROLE_OWNER
    )
    status = await service.status()
    return await inertia.render(
        c._PAGE_BILLING,
        {
            "status": status.model_dump(mode="json"),
            "plans": [p.model_dump(mode="json") for p in await service.public_plans()],
            "can_manage": can_manage,
            "csrf_token": get_csrf_token(request),
            "checkout": request.query_params.get("checkout", ""),
        },
    )
