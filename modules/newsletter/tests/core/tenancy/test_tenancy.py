"""Tenant binding: the scope, the two resolvers and the 403 envelope."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from simple_module_db.listeners import TenantIsolationError
from sm_newsletter.core.errors import install_exception_handlers
from sm_newsletter.core.tenancy import (
    TenancyMode,
    bind_admin,
    bind_public,
    bound_tenant,
    resolve_admin,
    resolve_public,
    tenant_scope,
)
from starlette.middleware.base import BaseHTTPMiddleware

pytestmark = pytest.mark.unbound_tenant


def test_scope_refuses_a_second_tenant():
    with tenant_scope("a"):
        with pytest.raises(TenantIsolationError), tenant_scope("b"):
            pass
        with tenant_scope("a") as again:
            assert again == "a"
        assert bound_tenant() == "a"


def test_invalid_tenant_refused():
    with pytest.raises(ValueError), tenant_scope("bad tenant!"):
        pass


class _Upstream(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        tenant = request.headers.get("x-up")
        if tenant:
            request.state.tenant_id = tenant
        request.state.user = SimpleNamespace(id="u")
        return await call_next(request)


def _app(mode: TenancyMode) -> FastAPI:
    app = FastAPI()
    app.state.sm_newsletter = SimpleNamespace(tenancy=mode)
    app.add_middleware(_Upstream)
    install_exception_handlers(app)

    @app.get("/admin", dependencies=[Depends(bind_admin)])
    async def admin():
        return {"tenant": bound_tenant()}

    @app.get("/public", dependencies=[Depends(bind_public)])
    async def public():
        return {"tenant": bound_tenant()}

    return app


async def _get(app: FastAPI, path: str, **headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path, headers=headers)


async def test_admin_single_mode_binds_default():
    got = await _get(_app(TenancyMode.SINGLE), "/admin")
    assert (got.status_code, got.json()) == (200, {"tenant": "default"})


async def test_admin_multi_without_tenant_is_403():
    got = await _get(_app(TenancyMode.MULTI), "/admin")
    assert got.status_code == 403
    body = got.json()
    assert body["code"] == "tenant_required"
    assert body["detail"]


async def test_public_without_tenant_is_none():
    request = SimpleNamespace(
        app=_app(TenancyMode.MULTI), state=SimpleNamespace(), scope={}, headers={}
    )
    assert resolve_public(request) is None
    got = await _get(_app(TenancyMode.MULTI), "/public")
    assert (got.status_code, got.json()["code"]) == (404, "not_found")


async def test_upstream_tenant_wins_in_single_mode():
    app = _app(TenancyMode.SINGLE)
    for path in ("/admin", "/public"):
        got = await _get(app, path, **{"x-up": "acme"})
        assert got.json() == {"tenant": "acme"}, path
    request = SimpleNamespace(app=app, state=SimpleNamespace(tenant_id="acme", user=1))
    assert resolve_admin(request) == resolve_public(request) == "acme"
