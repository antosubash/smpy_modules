"""Single scoped write path for pageviews and custom events."""

from datetime import datetime, timedelta

from simple_module_db import mark_written
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_analytics.collection.privacy import canonical_path, referrer_host, user_agent, visitor_key
from sm_analytics.core.geo import GeoResolver
from sm_analytics.models import AnalyticsEvent, AnalyticsProperty, AnalyticsSession
from sm_analytics.web.schemas import CollectIn


async def collect(
    db: AsyncSession,
    data: CollectIn,
    *,
    tenant: str,
    ip: str,
    ua: str,
    secret: str,
    geo: GeoResolver,
    now: datetime,
    source_origin: str | None = None,
) -> bool:
    # Serialize a property's writes, including on SQLite where FOR UPDATE is ignored.
    result = await db.execute(
        update(AnalyticsProperty)
        .where(
            AnalyticsProperty.id == data.property_id,
            AnalyticsProperty.tenant_id == tenant,
            AnalyticsProperty.enabled.is_(True),
        )
        .values(enabled=AnalyticsProperty.enabled)
    )
    if not result.rowcount:
        return False
    prop = await db.scalar(
        select(AnalyticsProperty)
        .where(AnalyticsProperty.id == data.property_id, AnalyticsProperty.tenant_id == tenant)
        .execution_options(populate_existing=True)
    )
    if source_origin is not None and source_origin not in prop.origins:
        return False
    path = canonical_path(data.path, prop.route_patterns, prop.kind)
    if path is None or (data.kind == "event" and data.name not in prop.event_allowlist):
        return False
    duplicate = await db.scalar(
        select(AnalyticsEvent.id).where(
            AnalyticsEvent.tenant_id == tenant,
            AnalyticsEvent.property_id == prop.id,
            AnalyticsEvent.event_id == str(data.event_id),
        )
    )
    if duplicate:
        return False
    browser, os, device = user_agent(ua)
    visitor = visitor_key(secret, tenant, prop.id, ip, browser, now)
    session = await db.scalar(
        select(AnalyticsSession)
        .where(
            AnalyticsSession.tenant_id == tenant,
            AnalyticsSession.property_id == prop.id,
            AnalyticsSession.visitor == visitor,
            AnalyticsSession.last_seen > now - timedelta(minutes=30),
        )
        .order_by(AnalyticsSession.last_seen.desc())
        .limit(1)
    )
    if session is None:
        session = AnalyticsSession(
            tenant_id=tenant, property_id=prop.id, visitor=visitor, started_at=now, last_seen=now
        )
        db.add(session)
        await db.flush()
    session.last_seen = now
    properties = {
        k: v for k, v in data.properties.items() if k in prop.event_allowlist.get(data.name, [])
    }
    utm = {k: v for k, v in data.utm.items() if k in prop.utm_parameters}
    location = geo.lookup(ip)
    db.add(
        AnalyticsEvent(
            tenant_id=tenant,
            property_id=prop.id,
            session_id=session.id,
            event_id=str(data.event_id),
            visitor=visitor,
            created_at=now,
            kind=data.kind,
            path=path,
            name=data.name,
            properties=properties,
            referrer=referrer_host(data.referrer),
            browser=browser,
            os=os,
            device=device,
            **utm,
            **location.fields(),
        )
    )
    await db.flush()
    mark_written(db)
    return True
