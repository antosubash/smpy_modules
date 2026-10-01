"""Tenant billing API (``/api/billing``). CSRF-checked on every mutation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_hosting.csrf import RequiresCsrf
from simple_module_hosting.permissions import RequiresPermission

from sm_billing import constants as c
from sm_billing.deps import BillingServiceDep, Owner, base_url, user_email
from sm_billing.schemas import PlanChoice, StatusOut, UrlOut

router = APIRouter(dependencies=[Depends(RequiresCsrf())])

_VIEW = [Depends(RequiresPermission(c.PERM_VIEW))]
_MANAGE = [Depends(RequiresPermission(c.PERM_MANAGE))]


@router.get("/status", response_model=StatusOut, dependencies=_VIEW)
async def status(service: BillingServiceDep) -> StatusOut:
    return await service.status()


@router.post("/checkout", response_model=UrlOut, dependencies=_MANAGE)
async def checkout(
    body: PlanChoice, request: Request, service: BillingServiceDep, _: Owner
) -> UrlOut:
    url = await service.checkout(
        body.plan_id, body.interval, email=user_email(request), base=base_url(request)
    )
    return UrlOut(url=url)


@router.post("/portal", response_model=UrlOut, dependencies=_MANAGE)
async def portal(request: Request, service: BillingServiceDep, _: Owner) -> UrlOut:
    return UrlOut(url=await service.portal(base=base_url(request)))


@router.post("/change-plan", response_model=StatusOut, dependencies=_MANAGE)
async def change_plan(body: PlanChoice, service: BillingServiceDep, _: Owner) -> StatusOut:
    return await service.change_plan(body.plan_id, body.interval)
