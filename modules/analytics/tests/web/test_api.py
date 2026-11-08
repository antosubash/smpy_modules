from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from simple_module_core.tenancy import TenancyMode
from simple_module_db import get_db
from simple_module_hosting.csrf import get_csrf_token
from sm_analytics.core.runtime import Runtime
from sm_analytics.core.settings import AnalyticsSettings
from sm_analytics.models import AnalyticsEvent
from sm_analytics.web.endpoints.admin import router as admin
from sm_analytics.web.endpoints.public import router as public
from sqlalchemy import func, select
from starlette.middleware.sessions import SessionMiddleware


@pytest_asyncio.fixture
async def client(factory):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-session-secret")

    @app.get("/test-csrf")
    async def csrf(request: Request):
        return {"token": get_csrf_token(request)}

    app.state.sm = SimpleNamespace(
        tenancy=TenancyMode.SINGLE, settings=SimpleNamespace(secret_key="test-secret")
    )
    app.state.sm_analytics = Runtime(AnalyticsSettings(geo_enabled=False))

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.tenant_id = request.headers.get("test-tenant", "default")
        request.state.user = SimpleNamespace(
            id="admin", roles=["admin"], permissions=[], scopes=None
        )
        request.state.resolved_permissions = set(
            request.headers.get("test-permissions", "*").split(",")
        )
        return await call_next(request)

    async def database():
        async with factory() as db:
            yield db
            await db.commit()

    app.dependency_overrides[get_db] = database
    app.include_router(admin, prefix="/api/analytics")
    app.include_router(public, prefix="/api/analytics")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://example.com"
    ) as value:
        value.headers["X-CSRF-Token"] = (await value.get("/test-csrf")).json()["token"]
        yield value


@pytest.mark.asyncio
async def test_opt_in_origin_privacy_and_no_cross_tenant_access(client, factory):
    data = {"name": "Public", "origins": ["https://example.com"], "route_patterns": ["/p/:slug"]}
    created = await client.post("/api/analytics/properties", json=data)
    assert created.status_code == 201, created.text
    prop = created.json()
    assert prop["enabled"] is False
    assert (await client.get("/api/analytics/config")).json() == {"properties": []}
    assert (
        await client.put(f"/api/analytics/properties/{prop['id']}", json=data | {"enabled": True})
    ).status_code == 200
    assert len((await client.get("/api/analytics/config")).json()["properties"]) == 1
    payload = {
        "property_id": prop["id"],
        "event_id": str(uuid4()),
        "kind": "pageview",
        "path": "/p/home",
    }
    for headers in ({}, {"origin": "https://evil.example"}):
        response = await client.post("/api/analytics/collect", headers=headers, json=payload)
        assert response.status_code in {204, 403}
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(AnalyticsEvent)) == 0
    for headers in (
        {"origin": "https://example.com", "dnt": "1"},
        {"origin": "https://example.com", "sec-gpc": "1"},
        {"origin": "https://example.com", "test-tenant": "other"},
    ):
        assert (
            await client.post("/api/analytics/collect", headers=headers, json=payload)
        ).status_code == 204
    accepted = await client.post(
        "/api/analytics/collect", headers={"origin": "https://example.com"}, json=payload
    )
    assert accepted.status_code == 204, accepted.text
    report = await client.get(f"/api/analytics/properties/{prop['id']}/report")
    assert report.status_code == 200 and report.json()["totals"]["pageviews"] == 1
    assert (
        await client.get(
            f"/api/analytics/properties/{prop['id']}/report", headers={"test-tenant": "other"}
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"/api/analytics/properties/{prop['id']}", headers={"test-tenant": "other"}
        )
    ).status_code == 404
    assert (
        await client.get("/api/analytics/properties", headers={"test-permissions": "unrelated"})
    ).status_code == 403
    assert (
        await client.post(
            "/api/analytics/properties", json=data, headers={"test-permissions": "analytics.view"}
        )
    ).status_code == 403
    assert (await client.delete(f"/api/analytics/properties/{prop['id']}")).status_code == 204
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(AnalyticsEvent)) == 0


@pytest.mark.asyncio
async def test_report_rejects_invalid_dates_and_preserves_unknown_filter(client):
    data = {"name": "Test", "origins": ["https://example.com"]}
    prop = (await client.post("/api/analytics/properties", json=data)).json()
    for query in ("start=2026-11-09&end=2026-11-08", "start=2020-01-01&end=2026-01-01"):
        assert (
            await client.get(f"/api/analytics/properties/{prop['id']}/report?{query}")
        ).status_code == 422


@pytest.mark.asyncio
async def test_report_minimum_date_is_not_an_internal_error(client):
    prop = (
        await client.post(
            "/api/analytics/properties", json={"name": "Test", "origins": ["https://example.com"]}
        )
    ).json()
    response = await client.get(f"/api/analytics/properties/{prop['id']}/report?end=0001-01-01")
    assert response.status_code == 200
    assert response.json()["series"] == [{"date": "0001-01-01", "pageviews": 0, "events": 0}]


@pytest.mark.asyncio
async def test_management_requires_session_csrf_but_collector_does_not(client):
    client.headers.pop("X-CSRF-Token")
    response = await client.post(
        "/api/analytics/properties", json={"name": "Protected", "origins": ["https://example.com"]}
    )
    assert response.status_code == 403
    response = await client.post(
        "/api/analytics/collect",
        headers={"origin": "https://example.com"},
        json={"property_id": "unknown", "event_id": str(uuid4()), "kind": "pageview", "path": "/"},
    )
    assert response.status_code == 204
