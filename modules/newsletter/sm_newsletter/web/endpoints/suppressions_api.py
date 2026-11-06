"""``/suppressions``: the listing, the lookup by address and the audited lift.

``bind_admin`` first on the router, then ``newsletter.manage`` on each route.
The lookup is a ``POST`` so an address never sits in a URL or an access log,
and no answer carries one.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sm_records.contracts.newsletter import caller_roles
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import clock, constants
from sm_newsletter.core.errors_audience import InvalidQuery
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.subscribers import lift as lifting
from sm_newsletter.subscribers import suppressions
from sm_newsletter.web.schemas.campaigns import parse_payload
from sm_newsletter.web.schemas.suppressions import (
    LiftIn,
    LiftOut,
    LiftPage,
    LookupIn,
    SuppressionOut,
    SuppressionPage,
)

router = APIRouter(dependencies=[Depends(bind_admin)])

_MANAGE = [Depends(RequiresPermission(constants.PERM_MANAGE))]
MAX_LIMIT = 100


@router.get("/suppressions", response_model=SuppressionPage, dependencies=_MANAGE)
async def list_suppressions(
    request: Request,
    tenant: str = Depends(bind_admin),
    reason: str | None = Query(None, max_length=64),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
) -> SuppressionPage:
    if reason is not None and reason not in constants.REASONS:
        raise InvalidQuery("reason: unknown")
    items, total, counts = await suppressions.list_suppressions(
        db,
        tenant_id=tenant,
        roles=caller_roles(request),
        reason=reason,
        offset=offset,
        limit=limit,
    )
    return SuppressionPage(items=[SuppressionOut.of(r) for r in items], total=total, counts=counts)


@router.post("/suppressions/lookup", response_model=list[SuppressionOut], dependencies=_MANAGE)
async def lookup(
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> list[SuppressionOut]:
    data = parse_payload(LookupIn, payload, error=InvalidQuery)
    rows = await suppressions.rows_for_email(
        db, tenant_id=tenant, roles=caller_roles(request), email=data.email
    )
    return [SuppressionOut.of(r) for r in rows]


@router.get("/suppressions/lifts", response_model=LiftPage, dependencies=_MANAGE)
async def list_lifts(
    request: Request,
    tenant: str = Depends(bind_admin),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
) -> LiftPage:
    items, total = await lifting.list_lifts(
        db, tenant_id=tenant, roles=caller_roles(request), offset=offset, limit=limit
    )
    return LiftPage(items=[LiftOut.of(i) for i in items], total=total)


@router.post("/suppressions/{suppression_id}/lift", response_model=LiftOut, dependencies=_MANAGE)
async def lift(
    suppression_id: int,
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> LiftOut:
    data = parse_payload(LiftIn, payload, error=InvalidQuery)
    row = await lifting.lift(
        db,
        tenant_id=tenant,
        roles=caller_roles(request),
        suppression_id=suppression_id,
        version=data.version,
        email=data.email,
        note=data.note,
        now=clock.utcnow(),
    )
    return LiftOut.of(row)
