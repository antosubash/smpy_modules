"""Platform-admin billing API (``/api/billing/admin``). CSRF-checked."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_db.deps import get_db
from simple_module_hosting.csrf import RequiresCsrf
from simple_module_hosting.permissions import RequiresPermission
from sqlalchemy.ext.asyncio import AsyncSession

from sm_billing import admin
from sm_billing import constants as c
from sm_billing.checkout import plan_out
from sm_billing.plans import PlanService
from sm_billing.schemas import (
    AssignIn,
    ConnectionIn,
    ConnectionOut,
    PlanIn,
    PlanOut,
    SubscriptionRow,
)

router = APIRouter(prefix="/admin", dependencies=[Depends(RequiresCsrf())])

_VIEW = [Depends(RequiresPermission(c.PERM_PLATFORM_VIEW))]
_MANAGE = [Depends(RequiresPermission(c.PERM_PLATFORM_MANAGE))]


@router.get("/plans", response_model=list[PlanOut], dependencies=_VIEW)
async def list_plans(db: AsyncSession = Depends(get_db)) -> list[PlanOut]:
    return [plan_out(p) for p in await PlanService(db).list()]


@router.post("/plans", response_model=PlanOut, status_code=201, dependencies=_MANAGE)
async def create_plan(
    body: PlanIn, request: Request, db: AsyncSession = Depends(get_db)
) -> PlanOut:
    return plan_out(await admin.save_plan(db, request.app, body, None))


@router.put("/plans/{plan_id}", response_model=PlanOut, dependencies=_MANAGE)
async def update_plan(
    plan_id: int, body: PlanIn, request: Request, db: AsyncSession = Depends(get_db)
) -> PlanOut:
    return plan_out(await admin.save_plan(db, request.app, body, plan_id))


@router.post("/plans/{plan_id}/archive", response_model=PlanOut, dependencies=_MANAGE)
async def archive_plan(plan_id: int, db: AsyncSession = Depends(get_db)) -> PlanOut:
    return plan_out(await PlanService(db).archive(plan_id))


@router.get("/subscriptions", response_model=list[SubscriptionRow], dependencies=_VIEW)
async def list_subscriptions(
    request: Request,
    status: str | None = None,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[SubscriptionRow]:
    return await admin.subscription_rows(db, request.app, status=status, offset=max(0, offset))


@router.post(
    "/subscriptions/{tenant_id}/assign", response_model=SubscriptionRow, dependencies=_MANAGE
)
async def assign(
    tenant_id: str, body: AssignIn, request: Request, db: AsyncSession = Depends(get_db)
) -> SubscriptionRow:
    await admin.assign(db, request.app, tenant_id, body)
    return await admin.one_row(db, request.app, tenant_id)


@router.post(
    "/subscriptions/{tenant_id}/resync", response_model=SubscriptionRow, dependencies=_MANAGE
)
async def resync(
    tenant_id: str, request: Request, db: AsyncSession = Depends(get_db)
) -> SubscriptionRow:
    await admin.resync(db, request.app, tenant_id)
    return await admin.one_row(db, request.app, tenant_id)


@router.get("/connection", response_model=ConnectionOut, dependencies=_VIEW)
async def get_connection(request: Request) -> ConnectionOut:
    return admin.connection_out(request.app)


@router.put("/connection", response_model=ConnectionOut, dependencies=_MANAGE)
async def put_connection(
    body: ConnectionIn, request: Request, db: AsyncSession = Depends(get_db)
) -> ConnectionOut:
    return await admin.save_connection(db, request.app, body)
