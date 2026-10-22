"""A tenant resolved upstream always wins, at request time (#192).

The mode detector reads only the app it is handed. A child app mounted under a
multi-tenant parent, or one whose ``TenantMiddleware`` is installed by a
factory, shows it no ``TenantMiddleware`` — and a ``SINGLE`` that bound
``default`` there would serve one tenant's rows to every other. These drive
real ASGI requests through the module's own binding dependencies.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from pagebuilder import tenancy
from pagebuilder.tenancy import DEFAULT_TENANT, TenancyMode
from simple_module_db import current_tenant_id, tenant_context

# No harness tenant: an ambient binding would be an upstream tenant, and win.
pytestmark = pytest.mark.unbound_tenant


class HeaderTenant:
    """A parent's tenant resolver: ``x-tenant`` onto ``state`` and the contextvar."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        raw = dict(scope.get("headers") or []).get(b"x-tenant")
        if scope["type"] != "http" or raw is None:
            await self.app(scope, receive, send)
            return
        scope.setdefault("state", {})["tenant_id"] = raw.decode()
        with tenant_context(raw.decode()):
            await self.app(scope, receive, send)


def _module_app() -> FastAPI:
    """What the module's routers look like: each surface behind its binder."""
    app = FastAPI()

    @app.get("/admin")
    async def admin(tenant: str = Depends(tenancy.bind_admin)) -> dict:
        return {"tenant": tenant, "bound": current_tenant_id.get()}

    @app.get("/public")
    async def public(tenant: str = Depends(tenancy.bind_public)) -> dict:
        return {"tenant": tenant, "bound": current_tenant_id.get()}

    @app.get("/cached")
    async def cached(request: Request, tenant: str = Depends(tenancy.bind_public)):
        response = JSONResponse({"tenant": tenant})
        response.headers["Cache-Control"] = "public, max-age=60"
        return tenancy.vary_on_tenant(response, request)

    return app


async def _get(app: FastAPI, path: str, tenant: str | None = None):
    headers = {"x-tenant": tenant} if tenant else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.get(path, headers=headers)


def _mounted_under_a_multi_tenant_parent() -> FastAPI:
    child = _module_app()
    assert tenancy.detect_mode(child) is TenancyMode.SINGLE  # what the child sees
    parent = FastAPI()
    parent.add_middleware(HeaderTenant)
    parent.mount("/child", child)
    return parent


@pytest.mark.parametrize("surface", ["admin", "public"])
async def test_a_mounted_child_binds_the_parents_tenant(surface):
    response = await _get(_mounted_under_a_multi_tenant_parent(), f"/child/{surface}", "tenant-a")
    assert response.status_code == 200, response.text
    assert response.json() == {"tenant": "tenant-a", "bound": "tenant-a"}


async def test_a_mounted_child_with_no_upstream_tenant_refuses():
    """Nothing visible says the parent is single-tenant, so it is not."""
    parent = _mounted_under_a_multi_tenant_parent()
    admin = await _get(parent, "/child/admin")
    public = await _get(parent, "/child/public")
    assert (admin.status_code, admin.json()["detail"]) == (403, tenancy.TENANT_REQUIRED)
    assert public.status_code == 404


def _factory(app):
    """``Middleware(factory)``: the stack entry is a function, not a class."""
    return HeaderTenant(app)


async def test_a_factory_built_middleware_is_multi():
    app = _module_app()
    app.add_middleware(_factory)
    assert tenancy.detect_mode(app) is TenancyMode.MULTI
    assert (await _get(app, "/admin")).status_code == 403
    response = await _get(app, "/admin", "tenant-b")
    assert response.json() == {"tenant": "tenant-b", "bound": "tenant-b"}


@pytest.mark.parametrize("surface", ["admin", "public"])
async def test_a_single_tenant_host_still_binds_the_default(surface):
    response = await _get(_module_app(), f"/{surface}")
    assert response.status_code == 200, response.text
    assert response.json() == {"tenant": DEFAULT_TENANT, "bound": DEFAULT_TENANT}


def test_media_serves_the_upstream_tenants_directory():
    """The media mount has no router dependency; the same rule holds there."""
    from pagebuilder.media_files import _serving_tenant

    single = FastAPI()
    assert _serving_tenant({"app": single, "state": {"tenant_id": "tenant-a"}}) == "tenant-a"
    with tenant_context("tenant-b"):
        assert _serving_tenant({"app": single}) == "tenant-b"
    assert _serving_tenant({"app": single}) == DEFAULT_TENANT
    assert _serving_tenant({}) is None  # no app is no answer, not single-tenant


def test_media_in_a_mounted_child_without_a_tenant_is_refused():
    """The media mount's own prefix is not "mounted"; a parent's mount is."""
    from pagebuilder.media_files import _serving_tenant

    single = FastAPI()
    own = {"app": single, "app_root_path": "", "root_path": "/media"}
    assert _serving_tenant(own, "/media") == DEFAULT_TENANT
    under_parent = {"app": single, "app_root_path": "", "root_path": "/child/media"}
    assert _serving_tenant(under_parent, "/media") is None


async def test_a_mounted_child_keys_the_cache_on_the_tenant():
    """A SINGLE-detected child serving the parent's tenant must not let a
    shared cache hand tenant A's response to tenant B (#192)."""
    response = await _get(_mounted_under_a_multi_tenant_parent(), "/child/cached", "tenant-a")
    assert response.json() == {"tenant": "tenant-a"}
    assert "Cookie" in response.headers["vary"]
    assert response.headers["cache-control"] == "private, max-age=60"


async def test_a_single_tenant_host_keeps_its_shared_cache():
    response = await _get(_module_app(), "/cached")
    assert "vary" not in response.headers
    assert response.headers["cache-control"] == "public, max-age=60"


async def test_media_through_a_parents_mount(tmp_path):
    """Real requests: the child's own media mount works single-tenant, and
    under a multi-tenant parent it serves the parent's tenant or nothing."""
    from pagebuilder.media_files import MediaFiles

    for tenant in (DEFAULT_TENANT, "tenant-a"):
        (tmp_path / tenant).mkdir()
        (tmp_path / tenant / "photo.jpg").write_bytes(tenant.encode())
    child = FastAPI()
    child.mount("/media", MediaFiles(directory=tmp_path), name="media")
    assert (await _get(child, "/media/photo.jpg")).content == DEFAULT_TENANT.encode()
    parent = FastAPI()
    parent.add_middleware(HeaderTenant)
    parent.mount("/child", child)
    assert (await _get(parent, "/child/media/photo.jpg")).status_code == 404
    response = await _get(parent, "/child/media/photo.jpg", "tenant-a")
    assert response.content == b"tenant-a"
