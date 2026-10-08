"""Tenancy core: mode detection, the startup refusal, request binding, SM024.

Isolation between two live tenants is covered by the ``test_tenancy_isolation*``
suites; this file pins the pieces they stand on.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from pagebuilder import tenancy
from pagebuilder.module import PagebuilderModule
from pagebuilder.tenancy import DEFAULT_TENANT, TenancyMode
from simple_module_core.diagnostics._tenancy import (
    check_tenant_unique_keys,
    module_tables,
)
from simple_module_db import current_tenant_id
from simple_module_hosting.middleware import TenantMiddleware
from tenant_app import multi_client

_TABLES = {
    "pagebuilder_pages",
    "pagebuilder_page_revisions",
    "pagebuilder_page_redirects",
    "pagebuilder_media",
    "pagebuilder_layout",
    "pagebuilder_layout_revisions",
    "pagebuilder_snapshots",
    "pagebuilder_snapshot_media",
    "pagebuilder_pending_imports",
}


# --- models -------------------------------------------------------------------


def test_every_table_is_tenant_owned():
    tables = module_tables(PagebuilderModule())
    assert {t.name for t in tables} == _TABLES
    for table in tables:
        column = table.c.tenant_id
        assert not column.nullable and column.index, table.name


def test_sm024_reports_nothing():
    tables = module_tables(PagebuilderModule())
    assert check_tenant_unique_keys(tables, "PageBuilder") == []


# --- mode ---------------------------------------------------------------------


def _app(**tenant_kwargs) -> FastAPI:
    app = FastAPI()
    app.add_middleware(TenantMiddleware, **tenant_kwargs)
    return app


def test_no_middleware_is_single():
    assert tenancy.detect_mode(FastAPI()) is TenancyMode.SINGLE


def test_fixed_default_is_single():
    assert tenancy.detect_mode(_app(fixed=DEFAULT_TENANT)) is TenancyMode.SINGLE


def test_resolving_middleware_is_multi():
    assert tenancy.detect_mode(_app(header="X-Tenant-ID")) is TenancyMode.MULTI
    assert tenancy.detect_mode(_app()) is TenancyMode.MULTI


def test_configure_refuses_a_host_pinned_elsewhere():
    with pytest.raises(RuntimeError, match="default_tenant='acme'"):
        tenancy.configure(_app(fixed="acme"))


def test_configure_stores_the_mode():
    app = _app()
    app.state.pagebuilder = SimpleNamespace()
    assert tenancy.configure(app) is TenancyMode.MULTI
    assert tenancy.mode_of(app) is TenancyMode.MULTI


# --- resolution ---------------------------------------------------------------


def _request(app: FastAPI, tenant: object = None) -> SimpleNamespace:
    return SimpleNamespace(app=app, state=SimpleNamespace(tenant_id=tenant))


def test_single_mode_resolves_default_whatever_the_request_says():
    app = FastAPI()
    assert tenancy.resolve_admin(_request(app, "acme")) == DEFAULT_TENANT
    assert tenancy.resolve_public(_request(app, None)) == DEFAULT_TENANT


def test_multi_mode_uses_the_resolved_tenant():
    app = _app()
    assert tenancy.resolve_admin(_request(app, "acme")) == "acme"
    assert tenancy.resolve_public(_request(app, "acme")) == "acme"


@pytest.mark.parametrize("value", [None, "", "x" * 51, "../etc"])
def test_multi_mode_without_a_tenant(value):
    app = _app()
    assert tenancy.resolve_public(_request(app, value)) is None
    with pytest.raises(HTTPException) as caught:
        tenancy.resolve_admin(_request(app, value))
    assert caught.value.status_code == 403
    assert caught.value.detail == "tenant_required"


@pytest.mark.unbound_tenant
async def test_bind_public_binds_for_the_request_and_unbinds():
    app = _app()
    dep = tenancy.bind_public(_request(app, "acme"))
    assert await dep.__anext__() == "acme"
    assert current_tenant_id.get() == "acme"
    with pytest.raises(StopAsyncIteration):
        await dep.__anext__()
    assert current_tenant_id.get() is None


@pytest.mark.unbound_tenant
async def test_bind_public_404s_without_a_tenant():
    dep = tenancy.bind_public(_request(_app(), None))
    with pytest.raises(HTTPException) as caught:
        await dep.__anext__()
    assert caught.value.status_code == 404
    assert caught.value.detail == "Page not found"


# --- through real routes ------------------------------------------------------


@pytest.mark.unbound_tenant
@pytest.mark.parametrize("path", ["/p/about", "/sitemap.xml"])
async def test_public_route_without_tenant_is_404_not_500(tmp_path, path):
    async for client in multi_client(tmp_path, inject_user=False):
        response = await client.get(path)
        assert response.status_code == 404, response.text


@pytest.mark.unbound_tenant
async def test_admin_without_tenant_is_403(tmp_path):
    async for client in multi_client(tmp_path, inject_user=True):
        response = await client.get("/api/pagebuilder/pages")
        assert response.status_code == 403
        assert response.json()["detail"] == "tenant_required"


@pytest.mark.unbound_tenant
async def test_anonymous_admin_is_still_401(tmp_path):
    """The tenant check sits behind the auth check: 401 is the better answer."""
    async for client in multi_client(tmp_path, inject_user=False):
        response = await client.get("/api/pagebuilder/pages")
        assert response.status_code == 401


@pytest.mark.unbound_tenant
async def test_single_mode_routes_bind_the_default_tenant(authed_client):
    """With nothing bound by the test, a write only succeeds because the
    router bound :data:`DEFAULT_TENANT` — the column is ``NOT NULL``."""
    assert current_tenant_id.get() is None
    created = await authed_client.post(
        "/api/pagebuilder/pages", json={"title": "Hello", "slug": "hello"}
    )
    assert created.status_code == 201, created.text
    listed = await authed_client.get("/api/pagebuilder/pages")
    assert [p["slug"] for p in listed.json()["items"]] == ["hello"]
    assert (await authed_client.get("/p/hello")).status_code == 404  # a draft


# --- outside a request --------------------------------------------------------
