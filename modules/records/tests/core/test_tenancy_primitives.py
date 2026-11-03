"""Tenancy primitives — ``sm_records.core.tenancy`` (design 2026-09-23 §A.3, §A.4).

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
from sm_records.core import constants
from sm_records.web.endpoints.api._errors import RecordsErrorRoute
from sm_records.records.services.errors import Forbidden
from sm_records.core.tenancy import (
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

from tests.support.tenancy_primitives_cases import _real_app, _request, _UserFromHeader, _bound_app, _get, _REPO

pytestmark = pytest.mark.unbound_tenant


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


# --- resolvers ---------------------------------------------------------------


# --- the bind dependencies over a real request -------------------------------
