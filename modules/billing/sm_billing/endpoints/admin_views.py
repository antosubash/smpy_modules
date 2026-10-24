"""Platform-admin billing screens under ``/admin/billing``. Reads only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_core.permissions import grants
from simple_module_db.deps import get_db
from simple_module_hosting.csrf import get_csrf_token
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_hosting.permissions import RequiresPermission, resolved_permissions_for
from simple_module_inertia import InertiaResponse
from sqlalchemy.ext.asyncio import AsyncSession

from sm_billing import admin
from sm_billing import constants as c
from sm_billing.checkout import plan_out
from sm_billing.plans import PlanService

router = APIRouter(dependencies=[Depends(RequiresPermission(c.PERM_PLATFORM_VIEW))])


def known_limit_keys(app) -> list[str]:
    """The plan editor's suggestions: billing's own keys, then every registered meter."""
    registry = getattr(app.state, c.METERS_STATE_ATTR, None)
    meters = registry.keys() if registry is not None else []
    return list(dict.fromkeys([*c.KNOWN_LIMIT_KEYS, *meters]))


def _common(request: Request) -> dict:
    services = getattr(request.app.state, c.PACKAGE)
    return {
        "csrf_token": get_csrf_token(request),
        "can_manage": grants(resolved_permissions_for(request), c.PERM_PLATFORM_MANAGE),
        "provider": services.provider.name if services.provider else "",
        "checkout_available": bool(services.provider and services.provider.supports_checkout),
        # Why a chosen ``stripe`` fell back to ``manual``; "" when it did not (#200).
        "provider_error": services.provider_error,
    }


@router.get("/plans", response_model=None)
async def plans_page(
    request: Request, inertia: InertiaDep, db: AsyncSession = Depends(get_db)
) -> InertiaResponse:
    plans = [plan_out(p).model_dump(mode="json") for p in await PlanService(db).list()]
    return await inertia.render(
        c._PAGE_PLANS,
        {**_common(request), "plans": plans, "known_limit_keys": known_limit_keys(request.app)},
    )


@router.get("/subscriptions", response_model=None)
async def subscriptions_page(
    request: Request, inertia: InertiaDep, db: AsyncSession = Depends(get_db)
) -> InertiaResponse:
    status = request.query_params.get("status") or None
    rows = await admin.subscription_rows(db, request.app, status=status)
    plans = [plan_out(p).model_dump(mode="json") for p in await PlanService(db).list()]
    return await inertia.render(
        c._PAGE_SUBSCRIPTIONS,
        {
            **_common(request),
            "rows": [r.model_dump(mode="json") for r in rows],
            "plans": plans,
            "status_filter": status or "",
            "sync_health": (await admin.sync_health(db, request.app)).model_dump(mode="json"),
        },
    )


@router.get("/connection", response_model=None)
async def connection_page(request: Request, inertia: InertiaDep) -> InertiaResponse:
    return await inertia.render(
        c._PAGE_CONNECTION,
        {
            **_common(request),
            "connection": admin.connection_out(request.app).model_dump(mode="json"),
            "webhook_url": str(request.base_url).rstrip("/") + c.WEBHOOK_PATH,
        },
    )
