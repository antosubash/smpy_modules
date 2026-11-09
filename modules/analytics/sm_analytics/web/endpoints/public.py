"""Anonymous same-origin configuration and write-only collection."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from simple_module_db import get_db
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_analytics.collection.service import collect
from sm_analytics.core.tenancy import bind_public
from sm_analytics.models import AnalyticsProperty
from sm_analytics.web.deps import services, tenant_id
from sm_analytics.web.schemas import CollectIn, origin

router = APIRouter(dependencies=[Depends(bind_public)])


def request_origin(request: Request, *, required: bool) -> str:
    value = request.headers.get("origin")
    if not value and not required:
        value = str(request.base_url)
    try:
        return origin(value or "")
    except ValueError as exc:
        raise HTTPException(403, "Invalid origin") from exc


@router.get("/config")
async def config(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    source = request_origin(request, required=False)
    properties = (
        await db.scalars(
            select(AnalyticsProperty).where(
                AnalyticsProperty.tenant_id == tenant_id(), AnalyticsProperty.enabled.is_(True)
            )
        )
    ).all()
    return {
        "properties": [
            {
                key: getattr(p, key)
                for key in ("id", "kind", "route_patterns", "utm_parameters", "event_allowlist")
            }
            for p in properties
            if source in p.origins
        ]
    }


@router.post("/collect", status_code=204)
async def ingest(data: CollectIn, request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    source = request_origin(request, required=True)
    if request.headers.get("dnt") == "1" or request.headers.get("sec-gpc") == "1":
        return Response(status_code=204)
    ua = request.headers.get("user-agent", "")[:1000]
    if any(token in ua.lower() for token in ("bot", "crawler", "spider")):
        return Response(status_code=204)
    state = services(request)
    state.geo.path = state.settings.geo_database_path
    state.geo.enabled = state.settings.geo_enabled
    client = request.client.host if request.client else ""
    secret = request.app.state.sm.settings.secret_key
    await collect(
        db,
        data,
        tenant=tenant_id(),
        ip=client,
        ua=ua,
        secret=secret,
        geo=state.geo,
        now=datetime.now(UTC),
        source_origin=source,
    )
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
