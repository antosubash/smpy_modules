"""Tenancy core: mode detection, the startup refusal, request binding.

Route-level and isolation coverage arrives with the models and routers.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from news import tenancy
from news.tenancy import DEFAULT_TENANT, TenancyMode
from simple_module_db import current_tenant_id, tenant_context
from simple_module_hosting.middleware import TenantMiddleware


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


def test_configure_stores_the_mode_on_news_state():
    app = _app()
    app.state.news = SimpleNamespace()
    assert tenancy.configure(app) is TenancyMode.MULTI
    assert app.state.news.tenancy is TenancyMode.MULTI
    assert tenancy.mode_of(app) is TenancyMode.MULTI


def test_configure_without_news_state_uses_fallback_attribute():
    app = _app()
    assert tenancy.configure(app) is TenancyMode.MULTI
    assert app.state.news_tenancy is TenancyMode.MULTI
    assert tenancy.mode_of(app) is TenancyMode.MULTI


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
    dep = tenancy.bind_public(_request(_app(), "acme"))
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
    assert caught.value.detail == "Article not found"


@pytest.mark.unbound_tenant
async def test_bind_admin_binds_the_default_in_single_mode():
    dep = tenancy.bind_admin(_request(FastAPI(), None))
    assert await dep.__anext__() == DEFAULT_TENANT
    assert current_tenant_id.get() == DEFAULT_TENANT
    with pytest.raises(StopAsyncIteration):
        await dep.__anext__()


@pytest.mark.unbound_tenant
def test_search_tenant_falls_back_to_default():
    assert tenancy.search_tenant() == "default"
    with tenant_context("acme"):
        assert tenancy.search_tenant() == "acme"
