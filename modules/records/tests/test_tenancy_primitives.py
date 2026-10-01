"""Tenancy primitives — ``sm_records.tenancy`` (design 2026-09-23 §A.3, §A.4).

These pin the pieces the module's routers stand on: the scope's
set/reset/refusal, the tenant-id grammar, mode detection on the stacks the
framework actually builds, the two resolvers' table, and the bind dependencies
over a real request. The routers themselves are ``test_tenancy_binding.py``.

Every test runs **unbound** — the suite-wide ``default`` binding of
``conftest._default_tenant`` would make "nothing is bound" untestable.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from simple_module_db.listeners import TenantIsolationError, current_tenant_id
from simple_module_hosting.middleware import TenantMiddleware
from sm_records import constants
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.services.errors import Forbidden
from sm_records.tenancy import (
    ALL_TENANTS,
    DEFAULT_TENANT,
    TENANT_RE,
    TenancyMode,
    TenantRequired,
    TenantUnbound,
    all_tenants,
    bind_admin,
    bind_public,
    bound_tenant,
    configure,
    detect_mode,
    mode_of,
    resolve_admin,
    resolve_public,
    tenant_header,
    tenant_scope,
)
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

pytestmark = pytest.mark.unbound_tenant

_REPO = Path(__file__).resolve().parents[3]


# --- tenant_scope / bound_tenant -------------------------------------------


def test_the_scope_binds_and_always_resets():
    assert current_tenant_id.get() is None
    with tenant_scope("acme") as tenant:
        assert tenant == "acme" == bound_tenant()
    assert current_tenant_id.get() is None
    with pytest.raises(RuntimeError, match="boom"), tenant_scope("acme"):
        raise RuntimeError("boom")
    assert current_tenant_id.get() is None


def test_re_entering_the_bound_tenant_is_allowed_and_another_is_refused():
    with tenant_scope("acme"):
        with tenant_scope("acme"):
            assert bound_tenant() == "acme"
        assert bound_tenant() == "acme", "the inner scope reset what the outer one set"
        with pytest.raises(TenantIsolationError), tenant_scope("globex"):
            pass
        assert bound_tenant() == "acme"


def test_unbound_is_an_error_not_a_none():
    with pytest.raises(TenantUnbound):
        bound_tenant()


@pytest.mark.parametrize("value", ["", " acme", "-x", "_x", "a b", "a/b", "é", "x" * 51])
def test_the_scope_refuses_a_malformed_tenant(value):
    with pytest.raises(ValueError), tenant_scope(value):
        pass
    assert current_tenant_id.get() is None


@pytest.mark.parametrize("value", ["default", "acme", "A", "a1_b.c:d-e", "x" * 50])
def test_the_grammar_accepts_what_a_header_or_user_row_plausibly_holds(value):
    assert TENANT_RE.match(value)


def test_all_tenants_tags_the_statement():
    stmt = all_tenants(select(1))
    assert stmt.get_execution_options()[ALL_TENANTS] is True


# --- mode ------------------------------------------------------------------


def _real_app(monkeypatch, *, multi: bool):
    """``create_app`` — the stack the framework really builds. It resolves the
    host's templates from the project root it computed at import (the working
    directory then), so that is pointed at this repo's root."""
    if not (_REPO / "host" / "templates").is_dir():  # pragma: no cover - module-only checkout
        pytest.skip("no host checkout to build a real app from")
    from simple_module_hosting import Settings, app_builder, create_app

    monkeypatch.setattr(app_builder, "_PROJECT_ROOT", _REPO)
    return create_app(
        Settings(
            environment="testing",
            secret_key="tenancy-test",
            multi_tenant=multi,
            tenant_header="X-Tenant-ID" if multi else "",
        )
    )


@pytest.mark.parametrize("multi", [False, True])
def test_mode_is_read_off_the_stack_create_app_builds(monkeypatch, multi):
    app = _real_app(monkeypatch, multi=multi)
    assert detect_mode(app) is (TenancyMode.MULTI if multi else TenancyMode.SINGLE)
    # The header the public API names in ``Vary`` (§H) is the one the host gave
    # its ``TenantMiddleware`` — read off the same stack entry.
    assert tenant_header(app) == ("X-Tenant-ID" if multi else None)


def test_configure_stores_the_mode_and_warns_when_the_setting_asked_for_tenancy(caplog):
    """Only one disagreement is worth a warning: ``multi_tenant`` on in the
    database with no ``TenantMiddleware`` in the stack (an admin-UI edit that
    did nothing until a restart). A multi stack with the setting off says
    nothing either: the stack, not the setting, is what resolves tenants."""
    single = FastAPI()
    services = SimpleNamespace(tenancy=None)
    setattr(single.state, constants.PACKAGE, services)
    single.state.host = SimpleNamespace(settings=SimpleNamespace(multi_tenant=True))
    with caplog.at_level(logging.WARNING, logger="sm_records.tenancy"):
        assert configure(single) is TenancyMode.SINGLE
    assert services.tenancy is TenancyMode.SINGLE
    assert "multi_tenant is on" in caplog.text

    multi = FastAPI()
    multi.add_middleware(TenantMiddleware, header="X-Tenant-ID")
    setattr(multi.state, constants.PACKAGE, SimpleNamespace(tenancy=None))
    for wanted in (False, True):
        caplog.clear()
        multi.state.host = SimpleNamespace(settings=SimpleNamespace(multi_tenant=wanted))
        with caplog.at_level(logging.WARNING, logger="sm_records.tenancy"):
            assert configure(multi) is TenancyMode.MULTI
        assert caplog.text == ""


def test_a_host_pinned_to_default_is_single_and_any_other_pin_is_refused():
    """Framework 0.0.35 (#359): ``default_tenant`` without ``multi_tenant``
    installs ``TenantMiddleware(fixed=…)``. One tenant, so records' single mode
    — which only works when that tenant is the one records runs in."""
    pinned = FastAPI()
    pinned.add_middleware(TenantMiddleware, fixed=DEFAULT_TENANT)
    setattr(pinned.state, constants.PACKAGE, SimpleNamespace(tenancy=None))
    assert configure(pinned) is TenancyMode.SINGLE
    assert tenant_header(pinned) is None

    elsewhere = FastAPI()
    elsewhere.add_middleware(TenantMiddleware, fixed="acme")
    setattr(elsewhere.state, constants.PACKAGE, SimpleNamespace(tenancy=None))
    with pytest.raises(RuntimeError, match="default_tenant='acme'"):
        configure(elsewhere)


def test_mode_of_prefers_the_stored_mode_and_detects_before_startup():
    app = FastAPI()
    setattr(app.state, constants.PACKAGE, SimpleNamespace(tenancy=None))
    assert mode_of(app) is TenancyMode.SINGLE
    getattr(app.state, constants.PACKAGE).tenancy = TenancyMode.MULTI
    assert mode_of(app) is TenancyMode.MULTI


# --- resolvers ---------------------------------------------------------------


def _request(mode: TenancyMode, *, user=None, state_tenant=None):
    services = SimpleNamespace(tenancy=mode)
    app = SimpleNamespace(state=SimpleNamespace(**{constants.PACKAGE: services}))
    return SimpleNamespace(app=app, state=SimpleNamespace(user=user, tenant_id=state_tenant))


def test_single_mode_pins_default_whatever_the_user_or_header_says():
    request = _request(
        TenancyMode.SINGLE, user=SimpleNamespace(tenant_id="acme"), state_tenant="globex"
    )
    assert resolve_admin(request) == DEFAULT_TENANT
    assert resolve_public(request) == DEFAULT_TENANT


def test_multi_mode_admin_is_the_users_own_tenant_never_the_header():
    user = SimpleNamespace(tenant_id="acme")
    assert resolve_admin(_request(TenancyMode.MULTI, user=user, state_tenant="globex")) == "acme"
    for tenant in (None, "not a tenant"):
        request = _request(
            TenancyMode.MULTI, user=SimpleNamespace(tenant_id=tenant), state_tenant="globex"
        )
        with pytest.raises(TenantRequired) as refused:
            resolve_admin(request)
        assert isinstance(refused.value, Forbidden)
        assert (refused.value.status_code, refused.value.code) == (403, "tenant_required")
    with pytest.raises(HTTPException) as anonymous:
        resolve_admin(_request(TenancyMode.MULTI))
    assert anonymous.value.status_code == 401


def test_multi_mode_public_is_the_resolved_tenant_or_nothing():
    assert resolve_public(_request(TenancyMode.MULTI, state_tenant="acme")) == "acme"
    assert resolve_public(_request(TenancyMode.MULTI)) is None
    assert resolve_public(_request(TenancyMode.MULTI, state_tenant="../etc")) is None


# --- the bind dependencies over a real request -------------------------------


class _UserFromHeader(BaseHTTPMiddleware):
    """``X-Test-User-Tenant`` becomes a signed-in user with that tenant
    (``-`` for none) — outermost, where the framework's AuthMiddleware sits."""

    async def dispatch(self, request, call_next):  # type: ignore[override]
        raw = request.headers.get("X-Test-User-Tenant")
        if raw is not None:
            request.state.user = SimpleNamespace(tenant_id=None if raw == "-" else raw)
        return await call_next(request)


def _bound_app(*, multi: bool) -> FastAPI:
    app = FastAPI()
    for path, dependency in (("/admin", bind_admin), ("/public", bind_public)):
        router = APIRouter(route_class=RecordsErrorRoute, dependencies=[Depends(dependency)])

        @router.get(path)
        async def seen() -> dict:
            return {"tenant": current_tenant_id.get()}

        app.include_router(router)
    if multi:
        app.add_middleware(TenantMiddleware, header="X-Tenant-ID")
    app.add_middleware(_UserFromHeader)
    return app


async def _get(app: FastAPI, path: str, **headers: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.get(path, headers=headers)


async def test_single_mode_binds_default_for_the_request_and_resets_after():
    app = _bound_app(multi=False)
    for path in ("/admin", "/public"):
        response = await _get(app, path, **{"X-Tenant-ID": "acme", "X-Test-User-Tenant": "acme"})
        assert response.json() == {"tenant": DEFAULT_TENANT}
    assert current_tenant_id.get() is None


async def test_multi_mode_binds_the_users_tenant_and_refuses_a_user_without_one():
    app = _bound_app(multi=True)
    ok = await _get(app, "/admin", **{"X-Test-User-Tenant": "acme", "X-Tenant-ID": "globex"})
    assert ok.json() == {"tenant": "acme"}
    refused = await _get(app, "/admin", **{"X-Test-User-Tenant": "-", "X-Tenant-ID": "globex"})
    assert refused.status_code == 403
    assert refused.json()["code"] == "tenant_required"
    assert current_tenant_id.get() is None


async def test_multi_mode_public_reads_follow_the_header_and_404_without_one():
    app = _bound_app(multi=True)
    assert (await _get(app, "/public", **{"X-Tenant-ID": "acme"})).json() == {"tenant": "acme"}
    missing = await _get(app, "/public")
    assert (missing.status_code, missing.json()) == (404, {"detail": "not found"})
    malformed = await _get(app, "/public", **{"X-Tenant-ID": "a b"})
    assert malformed.status_code == 404
    assert current_tenant_id.get() is None
