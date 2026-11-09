"""Tenant-scoped property management and reporting."""

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from simple_module_db import get_db, mark_written
from simple_module_hosting.csrf import RequiresCsrf
from simple_module_hosting.permissions import RequiresPermission
from sqlalchemy import delete, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_analytics.core import constants
from sm_analytics.core.tenancy import bind_admin
from sm_analytics.models import AnalyticsEvent, AnalyticsProperty, AnalyticsSession
from sm_analytics.reporting.reports import report
from sm_analytics.web.deps import property_for, services, tenant_id
from sm_analytics.web.schemas import PropertyIn

_VIEW = Depends(RequiresPermission(constants.PERM_VIEW))
_MANAGE = Depends(RequiresPermission(constants.PERM_MANAGE))
_CSRF = Depends(RequiresCsrf())
router = APIRouter(dependencies=[Depends(bind_admin)])


@router.get("/properties", dependencies=[_VIEW])
async def properties(db: AsyncSession = Depends(get_db)) -> list[AnalyticsProperty]:
    return list(
        (
            await db.scalars(
                select(AnalyticsProperty)
                .where(AnalyticsProperty.tenant_id == tenant_id())
                .order_by(AnalyticsProperty.name)
            )
        ).all()
    )


@router.post("/properties", dependencies=[_MANAGE, _CSRF], status_code=201)
async def create(data: PropertyIn, db: AsyncSession = Depends(get_db)) -> AnalyticsProperty:
    prop = AnalyticsProperty(tenant_id=tenant_id(), **data.model_dump())
    db.add(prop)
    await db.flush()
    return prop


@router.put("/properties/{property_id}", dependencies=[_MANAGE, _CSRF])
async def update(
    property_id: str, data: PropertyIn, db: AsyncSession = Depends(get_db)
) -> AnalyticsProperty:
    prop = await property_for(db, property_id)
    for key, value in data.model_dump().items():
        setattr(prop, key, value)
    await db.flush()
    return prop


@router.delete("/properties/{property_id}", dependencies=[_MANAGE, _CSRF], status_code=204)
async def remove(property_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    # Take the same parent lock as collection before taking child deletion snapshots.
    locked = await db.execute(
        sql_update(AnalyticsProperty)
        .where(AnalyticsProperty.id == property_id, AnalyticsProperty.tenant_id == tenant_id())
        .values(enabled=False)
    )
    if not locked.rowcount:
        raise HTTPException(404, "Not found")
    prop = await property_for(db, property_id)
    for model in (AnalyticsEvent, AnalyticsSession):
        await db.execute(
            delete(model).where(model.tenant_id == tenant_id(), model.property_id == prop.id)
        )
    await db.delete(prop)
    await db.flush()
    mark_written(db)
    return Response(status_code=204)


@router.get("/status", dependencies=[_VIEW])
async def status(request: Request) -> dict:
    state = services(request)
    state.geo.path = state.settings.geo_database_path
    state.geo.enabled = state.settings.geo_enabled
    return {"geo": state.geo.status()}


@router.get("/properties/{property_id}/report", dependencies=[_VIEW])
async def read_report(
    property_id: str,
    response: Response,
    start: date | None = None,
    end: date | None = None,
    path: str | None = Query(None, max_length=500),
    event: str | None = Query(None, max_length=50),
    country: str | None = Query(None, max_length=2),
    region: str | None = Query(None, max_length=20),
    city: str | None = Query(None, max_length=20),
    db: AsyncSession = Depends(get_db),
) -> dict:
    prop = await property_for(db, property_id)
    end = end or datetime.now(UTC).date()
    start = start or end - timedelta(days=min(6, (end - date.min).days))
    if end < start:
        raise HTTPException(422, "Report end date must be on or after start date")
    if (end - start).days > 365 or end >= date.max:
        raise HTTPException(422, "Report dates must span at most 366 days")
    response.headers["Cache-Control"] = "private, no-store"
    return await report(
        db,
        tenant_id(),
        prop,
        start=start,
        end=end,
        filters={"path": path, "event": event, "country": country, "region": region, "city": city},
    )
