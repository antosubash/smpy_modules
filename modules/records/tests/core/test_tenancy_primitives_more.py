"""test_tenancy_primitives cases."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from simple_module_db.listeners import current_tenant_id
from simple_module_hosting.middleware import TenantMiddleware
from sm_records.core import constants
from sm_records.core.tenancy import (
    DEFAULT_TENANT,
    TenancyMode,
    TenantRequired,
    configure,
    mode_of,
    resolve_admin,
    resolve_public,
    tenant_header,
    tenant_scope,
)
from sm_records.records.services.errors import Forbidden

from tests.support.tenancy_primitives_cases import (
    _bound_app,
    _get,
    _request,
)

pytestmark = pytest.mark.unbound_tenant


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
    with pytest.raises(RuntimeError, match=r"TenantMiddleware\(fixed='acme'\)"):
        configure(elsewhere)


def test_mode_of_prefers_the_stored_mode_and_detects_before_startup():
    app = FastAPI()
    setattr(app.state, constants.PACKAGE, SimpleNamespace(tenancy=None))
    assert mode_of(app) is TenancyMode.SINGLE
    getattr(app.state, constants.PACKAGE).tenancy = TenancyMode.MULTI
    assert mode_of(app) is TenancyMode.MULTI


def test_single_mode_pins_default_whatever_the_user_says():
    request = _request(TenancyMode.SINGLE, user=SimpleNamespace(tenant_id="acme"))
    assert resolve_admin(request) == DEFAULT_TENANT
    assert resolve_public(request) == DEFAULT_TENANT
    # No user at all is still ``default`` on a single-tenant host.
    assert resolve_admin(_request(TenancyMode.SINGLE)) == DEFAULT_TENANT


def test_an_upstream_tenant_beats_a_single_detection():
    """Fail closed (#112, #192): a mode detection that wrongly says SINGLE —
    a mounted child app, a composed stack — must not override the tenant the
    parent already resolved, from ``request.state`` or the bound contextvar."""
    request = _request(TenancyMode.SINGLE, user=SimpleNamespace(), state_tenant="globex")
    assert resolve_admin(request) == "globex"
    assert resolve_public(request) == "globex"
    with tenant_scope("acme"):
        assert resolve_admin(_request(TenancyMode.SINGLE)) == "acme"
        assert resolve_public(_request(TenancyMode.SINGLE)) == "acme"
    # A malformed upstream value is no tenant, and the gap is filled as before.
    assert resolve_admin(_request(TenancyMode.SINGLE, state_tenant="a b")) == DEFAULT_TENANT


def test_multi_mode_admin_is_the_framework_resolved_tenant():
    """#112: the tenant ``TenantMiddleware`` resolved, as pagebuilder binds —
    not the user's ``tenant_id``, which can lag the active organisation."""
    user = SimpleNamespace(tenant_id="acme")
    assert resolve_admin(_request(TenancyMode.MULTI, user=user, state_tenant="globex")) == "globex"
    for resolved in (None, "not a tenant", "x" * 51):
        request = _request(TenancyMode.MULTI, user=user, state_tenant=resolved)
        with pytest.raises(TenantRequired) as refused:
            resolve_admin(request)
        assert isinstance(refused.value, Forbidden)
        # pagebuilder's and news' ``TENANT_REQUIRED``: one status and code for
        # "no tenant" across every module's admin surface.
        assert (refused.value.status_code, refused.value.code) == (403, "tenant_required")
    with pytest.raises(HTTPException) as anonymous:
        resolve_admin(_request(TenancyMode.MULTI))
    assert anonymous.value.status_code == 401


def test_multi_mode_public_is_the_resolved_tenant_or_nothing():
    assert resolve_public(_request(TenancyMode.MULTI, state_tenant="acme")) == "acme"
    assert resolve_public(_request(TenancyMode.MULTI)) is None
    assert resolve_public(_request(TenancyMode.MULTI, state_tenant="../etc")) is None


async def test_single_mode_binds_default_for_the_request_and_resets_after():
    app = _bound_app(multi=False)
    for path in ("/admin", "/public"):
        response = await _get(app, path, **{"X-Tenant-ID": "acme", "X-Test-User-Tenant": "acme"})
        assert response.json() == {"tenant": DEFAULT_TENANT}
    assert current_tenant_id.get() is None


async def test_multi_mode_binds_the_resolved_tenant_and_refuses_a_user_without_one():
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
