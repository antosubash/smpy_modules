"""Tenant billing API (``/api/billing``). CSRF-checked on every mutation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_core.permissions import grants
from simple_module_hosting.csrf import RequiresCsrf
from simple_module_hosting.permissions import RequiresPermission, resolved_permissions_for

from sm_billing import constants as c
from sm_billing.deps import (
    BillingServiceDep,
    Context,
    ContextServiceDep,
    Owner,
    base_url,
    user_email,
)
from sm_billing.errors import BillingError
from sm_billing.schemas import PlanChoice, StatusOut, UrlOut

router = APIRouter(dependencies=[Depends(RequiresCsrf())])

_MANAGE = [Depends(RequiresPermission(c.PERM_MANAGE))]


@router.get("/status", response_model=StatusOut)
async def status(request: Request, ctx: Context, service: ContextServiceDep) -> StatusOut:
    if not ctx.restore:
        _require(request, c.PERM_VIEW)
    return await service.status()


@router.post("/checkout", response_model=UrlOut, dependencies=_MANAGE)
async def checkout(
    body: PlanChoice, request: Request, service: BillingServiceDep, _: Owner
) -> UrlOut:
    url = await service.checkout(
        body.plan_id, body.interval, email=user_email(request), base=base_url(request)
    )
    return UrlOut(url=url)


@router.post("/portal", response_model=UrlOut)
async def portal(request: Request, ctx: Context, service: ContextServiceDep) -> UrlOut:
    """Also open to the owner of a billing-suspended tenant — it is how they pay."""
    if ctx.role != c.TENANT_ROLE_OWNER:
        raise BillingError("tenant_owner_required", 403)
    if not ctx.restore:
        _require(request, c.PERM_MANAGE)
    return UrlOut(url=await service.portal(base=base_url(request)))


def _require(request: Request, permission: str) -> None:
    if not grants(resolved_permissions_for(request), permission):
        raise BillingError("forbidden", 403)


@router.post("/change-plan", response_model=StatusOut, dependencies=_MANAGE)
async def change_plan(body: PlanChoice, service: BillingServiceDep, _: Owner) -> StatusOut:
    return await service.change_plan(body.plan_id, body.interval)
