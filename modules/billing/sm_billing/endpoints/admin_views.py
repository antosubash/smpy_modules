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

from sm_billing import admin, subjects
from sm_billing import constants as c
from sm_billing.checkout import plan_out
from sm_billing.metering import admin as usage_admin
from sm_billing.metering.report import overview, page_numbers
from sm_billing.plans import PlanService
from sm_billing.schemas import SubscriptionPageOut

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
        # "user": the lists name users (by email) instead of organisations (#274).
        "subject_mode": subjects.subject_mode(request.app),
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
    search = (request.query_params.get("q") or "").strip()
    total = await admin.subscription_count(db, request.app, status=status, q=search)
    served, pages = page_numbers(total, _page(request.query_params.get("page")), c.ADMIN_PAGE_SIZE)
    rows = await admin.subscription_rows(
        db,
        request.app,
        status=status,
        q=search,
        limit=c.ADMIN_PAGE_SIZE,
        offset=(served - 1) * c.ADMIN_PAGE_SIZE,
    )
    page = SubscriptionPageOut(
        items=rows, total=total, page=served, per_page=c.ADMIN_PAGE_SIZE, pages=pages
    )
    plans = [plan_out(p).model_dump(mode="json") for p in await PlanService(db).list()]
    return await inertia.render(
        c._PAGE_SUBSCRIPTIONS,
        {
            **_common(request),
            "subscriptions": page.model_dump(mode="json"),
            "plans": plans,
            "status_filter": status or "",
            "search": search,
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


def _flag(value: str | None) -> bool:
    return (value or "").lower() in ("1", "true", "on", "yes")


def _page(value: str | None) -> int:
    try:
        return max(1, min(int(value or 1), 1_000_000))
    except ValueError:
        return 1


@router.get("/usage", response_model=None)
async def usage_page(
    request: Request, inertia: InertiaDep, db: AsyncSession = Depends(get_db)
) -> InertiaResponse:
    """Tenant x meter for the current (or previous) period; the drawer's ledger
    and holds are fetched from ``/api/billing/admin/usage`` when it opens."""
    params = request.query_params
    meter = (params.get("meter") or "")[:64] or None
    query = (params.get("q") or "")[:120]
    period = "previous" if params.get("period") == "previous" else "current"
    over = _flag(params.get("over"))
    service = usage_admin.usage(request.app)
    rows = await overview(
        db,
        usage_admin.registry(request.app),
        service.now(),
        meter=meter,
        query=query,
        over=over,
        period=period,
        page=_page(params.get("page")),
    )
    return await inertia.render(
        c._PAGE_USAGE,
        {
            **_common(request),
            "usage": rows.model_dump(mode="json"),
            "meters": [m.model_dump(mode="json") for m in usage_admin.meters(request.app)],
            "filters": {"meter": meter or "", "q": query, "over": over, "period": period},
        },
    )
