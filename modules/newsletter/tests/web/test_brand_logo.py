"""``GET /newsletter/brand/logo``: the SYSTEM logo, anonymously, whatever the tenant (C8).

Branding's own ``/api/branding/logo`` is mounted beside it to show the tenant
override is really there: that route answers with the tenant's logo, this one
never does.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from branding.core.services import BrandingServices
from branding.core.settings import BrandingSettings
from branding.core.tenant_branding import merge
from branding.web.endpoints.assets import router as branding_assets
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from file_storage.files.downloads import StreamDownload
from file_storage.files.service import StoredFileNotFoundError
from file_storage.web.deps import get_file_storage_service
from httpx import ASGITransport, AsyncClient
from simple_module_core.public_routes import PublicRouteRegistry
from simple_module_db.listeners import current_tenant_id
from sm_newsletter.core import constants
from sm_newsletter.core.errors import install_exception_handlers
from sm_newsletter.module import NewsletterModule
from starlette.middleware.base import BaseHTTPMiddleware

pytestmark = pytest.mark.unbound_tenant

SYS = uuid.UUID("6f1c2b9e-1111-4c8e-9a3f-000000000001")
TENANT = uuid.UUID("6f1c2b9e-2222-4c8e-9a3f-000000000002")
URL = constants.BRAND_LOGO_PATH


class _Tenant(BaseHTTPMiddleware):
    """What the framework's subdomain resolution leaves behind: a tenant, no user."""

    async def dispatch(self, request, call_next):
        request.state.tenant_id = "acme"
        return await call_next(request)


class _Storage:
    """Platform files and one tenant's files; ``download`` keeps them apart as file_storage does."""

    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, bool]] = []

    async def download(self, file_id, *, platform=False, **_):
        self.calls.append((file_id, platform))
        files = {SYS: b"system-png"} if platform else {}
        if not platform and current_tenant_id.get() == "acme":
            files = {TENANT: b"tenant-png"}
        if file_id not in files:
            raise StoredFileNotFoundError(str(file_id))
        data = files[file_id]

        async def body():
            yield data

        row = SimpleNamespace(content_type="image/png", size_bytes=len(data), checksum_sha256="c")
        return StreamDownload(file=row, body=body())


def build(*, branding: BrandingSettings | None, override: bool = True) -> tuple[FastAPI, _Storage]:
    app = FastAPI()
    app.add_middleware(_Tenant)
    install_exception_handlers(app)
    app.state.sm = SimpleNamespace(settings=SimpleNamespace(multi_tenant=True, tenant_header=""))
    if branding is not None:
        app.state.branding = BrandingServices(settings=branding)
        if override:
            overrides = {"logo_file_id": str(TENANT)}
            app.state.branding.tenant_cache.entries["acme"] = (
                overrides,
                branding,
                merge(branding, "acme", overrides),
            )
    app.include_router(branding_assets, prefix="/api/branding")
    NewsletterModule.mount_public_routes(app)
    NewsletterModule.mount_public_routes(app)  # a lifespan restart mounts it once
    storage = _Storage()
    app.dependency_overrides[get_file_storage_service] = lambda: storage
    return app, storage


async def get(app: FastAPI, url: str):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://acme.example.org"
    ) as c:
        return await c.get(url)


async def test_serves_system_logo_despite_tenant_override():
    app, storage = build(branding=BrandingSettings(logo_file_id=str(SYS)))
    assert (await get(app, "/api/branding/logo")).content == b"tenant-png"  # the override is live
    res = await get(app, f"{URL}?v={SYS}")
    assert res.status_code == 200
    assert res.content == b"system-png"
    assert storage.calls[-1] == (SYS, True)
    assert res.headers["content-type"] == "image/png"
    assert "immutable" in res.headers["cache-control"]
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "no-cache" in (await get(app, URL)).headers["cache-control"]
    assert sum(r.path == URL for r in iter_route_contexts(app.routes)) == 1


async def test_404_without_branding_or_logo():
    app, _ = build(branding=None)
    assert (await get(app, URL)).status_code == 404
    app, _ = build(branding=BrandingSettings(), override=False)
    assert (await get(app, URL)).status_code == 404
    app, _ = build(branding=BrandingSettings(logo_file_id="not-a-uuid"), override=False)
    assert (await get(app, URL)).status_code == 404


async def test_404_when_system_file_missing():
    app, _ = build(branding=BrandingSettings(logo_file_id=str(TENANT)), override=False)
    assert (await get(app, URL)).status_code == 404  # a tenant's file id is no platform file


def test_route_is_public_get_only():
    registry = PublicRouteRegistry()
    NewsletterModule().register_public_routes(registry)
    assert registry.matches("GET", URL)
    assert not registry.matches("POST", URL)
    assert not registry.matches("GET", "/newsletter/brand/logo-x")
