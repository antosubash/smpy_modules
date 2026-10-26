"""Records fails closed where its view of the stack is incomplete (#210).

Two ways the app records is handed can hide a multi-tenant parent: a
``Middleware(factory)`` entry, which installs who-knows-what, and a ``Mount``
under a parent whose ``TenantMiddleware`` the child never sees. Both are
``MULTI`` unless the framework itself answers — the rule news and pagebuilder
follow (#192). The sidebar provider then has no tenant and lists no per-type
entries, and the role editor's per-type permissions lose their labels.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from simple_module_core.permissions import PermissionRegistry
from sm_records import constants, menu
from sm_records._permission_sync import PermissionSyncMiddleware
from sm_records.module import RecordsModule
from sm_records.services.errors import TenantRequired
from sm_records.settings import RecordsSettings
from sm_records.tenancy import (
    TenancyMode,
    detect_mode,
    resolve_admin,
    resolve_public,
    tenant_scope,
)
from starlette.applications import Starlette
from starlette.routing import Mount

from tests.app_harness import seed_type


class _Passthrough:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)


def _factory(app):
    """``Middleware(factory)``: the stack entry is a function, not a class."""
    return _Passthrough(app)


def test_a_factory_built_middleware_is_multi():
    app = FastAPI()
    app.add_middleware(_factory)
    assert detect_mode(app) is TenancyMode.MULTI


def test_a_factory_entry_on_an_app_create_app_built_is_the_frameworks_answer():
    """``state.sm`` says the framework can answer, and its answer is SINGLE."""
    app = FastAPI()
    app.state.sm = SimpleNamespace()
    app.add_middleware(_factory)
    assert detect_mode(app) is TenancyMode.SINGLE


def _request(app: FastAPI, scope: dict) -> SimpleNamespace:
    return SimpleNamespace(
        app=app, scope=scope, state=SimpleNamespace(tenant_id=None, user=object())
    )


@pytest.mark.unbound_tenant
def test_a_mounted_child_without_a_framework_answer_fails_closed():
    """A child ``create_app`` did not build (no ``state.sm``) has no framework
    answer, so mounted with no upstream tenant it is refused, not handed
    default; one ``create_app`` built answers ``SINGLE`` itself (0.0.36 floor,
    #211 — the 0.0.35 no-``tenancy_mode`` case no longer exists)."""
    app = FastAPI()
    request = _request(app, {"app_root_path": "", "root_path": "/child"})
    with pytest.raises(TenantRequired):
        resolve_admin(request)
    assert resolve_public(request) is None
    request.scope = {}  # not mounted: the app's own single-tenant answer stands
    assert resolve_admin(request) == "default"
    assert resolve_public(request) == "default"
    app.state.sm = SimpleNamespace(tenancy="single")
    request.scope = {"app_root_path": "", "root_path": "/child"}
    assert resolve_admin(request) == "default"


def _module(db_state: Any) -> RecordsModule:
    """A single-tenant module the way ``on_startup`` leaves one."""
    module = RecordsModule()
    module.settings = RecordsSettings(menu_refresh_seconds=0)
    module.db = db_state
    module.tenancy_mode = TenancyMode.SINGLE
    module.type_permissions.register(PermissionRegistry())
    return module


def _sidebar_app(module: RecordsModule) -> FastAPI:
    """A child app with the module's middleware, whose one route answers with
    what the sidebar provider and the role editor's source would show."""
    app = FastAPI()
    app.add_middleware(PermissionSyncMiddleware, module=module)

    @app.get("/admin/records/")
    async def sidebar(request: Request) -> dict[str, list]:
        request.state.user = SimpleNamespace(id="u", roles=["v"])
        request.state.resolved_permissions = {constants.PERM_VIEW}
        items = await menu.type_menu_provider(module, request)
        return {"menu": [item.label for item in items], "perms": list(module.type_permissions())}

    return app


async def _get(app: Any, path: str) -> dict[str, list]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.unbound_tenant
async def test_a_mounted_child_shows_no_default_tenant_types_or_labels(db_state):
    with tenant_scope("default"):
        await seed_type(db_state, "company", [], label_plural="Companies", show_in_menu=True)
    module = _module(db_state)
    child = _sidebar_app(module)
    parent = Starlette(routes=[Mount("/child", app=child)])

    served = await _get(parent, "/child/admin/records/")
    # No tenant the framework can vouch for: no per-type entries, per request.
    assert served["menu"] == []
    # The role editor is host-wide, so its source latches unlabelled: the
    # default tenant's type label must not name the parent's tenants' grants.
    assert served["perms"] == ["records.type.company"]
    assert module.type_permissions.ambiguous is True
    # Served directly afterwards, the sidebar is the default tenant's again —
    # nothing is process-wide any more — and the labels stay off.
    direct = await _get(child, "/admin/records/")
    assert direct["menu"] == ["Companies"]
    assert direct["perms"] == ["records.type.company"]


@pytest.mark.unbound_tenant
def test_a_mounted_childs_default_tenant_answer_is_never_shared():
    """The parent may have a tenant called ``default``: a mounted child's
    answer for it is private, not one shared cache entry for every tenant."""
    from sm_records.endpoints.api._public_cache import _tenancy

    request = _request(FastAPI(), {"app_root_path": "", "root_path": "/child"})
    request.state.tenant_id = "default"
    assert _tenancy(request) == (None, True)
    request.scope = {}  # served directly: the single-tenant host's shared answer
    assert _tenancy(request) == (None, False)


@pytest.mark.unbound_tenant
async def test_an_unmounted_single_tenant_sidebar_keeps_its_types(db_state):
    with tenant_scope("default"):
        await seed_type(db_state, "company", [], label_plural="Companies", show_in_menu=True)
    served = await _get(_sidebar_app(_module(db_state)), "/admin/records/")
    assert served["menu"] == ["Companies"]
    assert served["perms"] == [["records.type.company", "Records: Companies"]]
