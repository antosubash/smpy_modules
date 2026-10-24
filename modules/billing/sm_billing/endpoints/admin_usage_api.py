"""Platform-admin usage API (``/api/billing/admin/usage``). CSRF-checked.

Reads need ``billing.platform.view``; adjust, release and recount need
``billing.platform.manage``. Platform admin spans tenants, so the tenant is
the path's, and every query filters on it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from simple_module_db.deps import get_db
from simple_module_hosting.csrf import RequiresCsrf
from simple_module_hosting.permissions import RequiresPermission
from sqlalchemy.ext.asyncio import AsyncSession

from sm_billing import constants as c
from sm_billing.contracts.metering import MeterKind
from sm_billing.metering import admin as usage_admin
from sm_billing.metering.report import overview
from sm_billing.metering.schemas import (
    AdjustIn,
    AdjustOut,
    Period,
    RecountIn,
    RecountOut,
    ReleaseOut,
    UsageEventPageOut,
    UsageHoldOut,
    UsagePageOut,
)
from sm_billing.metering.validate import HOLD_ID_MAX, METER_MAX, TENANT_MAX

router = APIRouter(prefix="/admin/usage", dependencies=[Depends(RequiresCsrf())])

_VIEW = [Depends(RequiresPermission(c.PERM_PLATFORM_VIEW))]
_MANAGE = [Depends(RequiresPermission(c.PERM_PLATFORM_MANAGE))]

TenantId = Annotated[str, Path(min_length=1, max_length=TENANT_MAX)]
MeterQ = Annotated[str | None, Query(max_length=METER_MAX)]
PageQ = Annotated[int, Query(ge=1)]
PerPageQ = Annotated[int, Query(ge=1, le=100)]
HoldStatusQ = Literal["live", "held", "committed", "released", "expired"]
KindQ = Literal["consume", "record", "refund", "adjust"]


def _actor(request: Request) -> str | None:
    user = getattr(request.state, "user", None)
    return str(user.id) if user is not None and getattr(user, "id", None) else None


@router.get("", response_model=UsagePageOut, dependencies=_VIEW)
async def list_usage(
    request: Request,
    meter: MeterQ = None,
    q: Annotated[str, Query(max_length=120)] = "",
    over: bool = False,
    period: Period = "current",
    page: PageQ = 1,
    per_page: PerPageQ = 25,
    db: AsyncSession = Depends(get_db),
) -> UsagePageOut:
    service = usage_admin.usage(request.app)
    return await overview(
        db,
        usage_admin.registry(request.app),
        service.now(),
        meter=meter,
        query=q,
        over=over,
        period=period,
        page=page,
        per_page=per_page,
    )


@router.get("/{tenant_id}/events", response_model=UsageEventPageOut, dependencies=_VIEW)
async def list_events(
    tenant_id: TenantId,
    meter: MeterQ = None,
    kind: KindQ | None = None,
    page: PageQ = 1,
    per_page: PerPageQ = 25,
    db: AsyncSession = Depends(get_db),
) -> UsageEventPageOut:
    return await usage_admin.ledger(
        db, tenant_id, meter=meter, kind=kind, page=page, per_page=per_page
    )


@router.get("/{tenant_id}/holds", response_model=list[UsageHoldOut], dependencies=_VIEW)
async def list_holds(
    tenant_id: TenantId,
    meter: MeterQ = None,
    status: HoldStatusQ = "live",
    db: AsyncSession = Depends(get_db),
) -> list[UsageHoldOut]:
    return await usage_admin.holds(db, tenant_id, meter=meter, status=status)


@router.post("/{tenant_id}/adjust", response_model=AdjustOut, dependencies=_MANAGE)
async def adjust(
    tenant_id: TenantId, body: AdjustIn, request: Request, db: AsyncSession = Depends(get_db)
) -> AdjustOut:
    """Ledgered as ``adjust`` with the reason and the acting admin's id."""
    usage_admin.require_meter(request.app, body.meter, MeterKind.COUNTER)
    await usage_admin.require_tenant(db, request.app, tenant_id)
    used = await usage_admin.usage(request.app).adjust(
        tenant_id, body.meter, body.quantity, reason=body.reason, actor=_actor(request)
    )
    return AdjustOut(meter=body.meter, used=used)


@router.post("/{tenant_id}/recount", response_model=RecountOut, dependencies=_MANAGE)
async def recount(
    tenant_id: TenantId, body: RecountIn, request: Request, db: AsyncSession = Depends(get_db)
) -> RecountOut:
    """Rebuild a gauge's level from its live holds (repairs drift)."""
    usage_admin.require_meter(request.app, body.meter, MeterKind.GAUGE)
    await usage_admin.require_tenant(db, request.app, tenant_id)
    level = await usage_admin.usage(request.app).recount(tenant_id, body.meter)
    return RecountOut(meter=body.meter, in_use=level)


@router.post("/holds/{hold_id}/release", response_model=ReleaseOut, dependencies=_MANAGE)
async def release(
    hold_id: Annotated[str, Path(min_length=1, max_length=HOLD_ID_MAX)], request: Request
) -> ReleaseOut:
    """Return a hold's capacity; ``released: false`` when it was settled already."""
    return ReleaseOut(released=await usage_admin.usage(request.app).release(hold_id))
