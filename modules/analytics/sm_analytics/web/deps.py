"""Request-scoped settings and property access."""

from fastapi import HTTPException, Request
from simple_module_db import current_tenant_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_analytics.models import AnalyticsProperty


def tenant_id() -> str:
    tenant = current_tenant_id.get()
    if not tenant:
        raise RuntimeError("Analytics entry point did not bind a tenant")
    return tenant


async def property_for(db: AsyncSession, property_id: str) -> AnalyticsProperty:
    prop = await db.scalar(
        select(AnalyticsProperty).where(
            AnalyticsProperty.id == property_id, AnalyticsProperty.tenant_id == tenant_id()
        )
    )
    if prop is None:
        raise HTTPException(404, "Not found")
    return prop


def services(request: Request):
    return request.app.state.sm_analytics
