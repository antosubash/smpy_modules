"""Records fails closed where its view of the stack is incomplete (#210).

Two ways the app records is handed can hide a multi-tenant parent: a
``Middleware(factory)`` entry, which installs who-knows-what, and a ``Mount``
under a parent whose ``TenantMiddleware`` the child never sees. Both are
``MULTI`` unless the framework itself answers — the rule news and pagebuilder
follow (#192) — and the sidebar, which publishes into one process-wide
registry, drops its default-tenant per-type entries for the same reason.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection
from sm_records import constants, menu
from sm_records._menu_middleware import MenuSyncMiddleware
from sm_records.module import RecordsModule
from sm_records.services.errors import TenantRequired
from sm_records.settings import RecordsSettings
from sm_records.tenancy import TenancyMode, detect_mode, resolve_admin, resolve_public
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
def test_on_framework_0_0_35_a_mounted_child_fails_closed(monkeypatch):
    """No public ``tenancy_mode`` to ask: ``state.sm`` alone is no answer, so
    a mounted child with no upstream tenant is refused, not handed default."""
    monkeypatch.setitem(sys.modules, "simple_module_hosting.tenancy", None)  # ImportError
    app = FastAPI()
    app.state.sm = SimpleNamespace()
    request = _request(app, {"app_root_path": "", "root_path": "/child"})
    with pytest.raises(TenantRequired):
        resolve_admin(request)
    assert resolve_public(request) is None
    request.scope = {}  # not mounted: the app's own single-tenant answer stands
    assert resolve_admin(request) == "default"
    assert resolve_public(request) == "default"


def _hub() -> MenuItem:
    return MenuItem(
        label="All record types",
        url=constants.MENU_URL,
        icon=constants.MENU_ICON,
        order=constants.MENU_ORDER,
        section=MenuSection.ADMIN_SIDEBAR,
        group=constants.MENU_GROUP_TYPES,
    )


async def _synced_module(db_state: Any) -> RecordsModule:
    """A single-tenant module whose startup sync published a per-type entry."""
    await seed_type(db_state, "company", [], label_plural="Companies", show_in_menu=True)
    module = RecordsModule()
    module.settings = RecordsSettings(menu_refresh_seconds=0)
    module.db = db_state
    module.tenancy_mode = TenancyMode.SINGLE
    module.menu_registry = MenuRegistry()
    module.menu_registry.add(_hub())
    assert await menu.refresh(module, force=True) is True
    return module


def _sidebar_app(module: RecordsModule) -> FastAPI:
    app = FastAPI()
    app.add_middleware(MenuSyncMiddleware, module=module)

    @app.get("/admin/records/")
    async def sidebar(request: Request) -> list[str]:
        return [item.label for item in module.menu_registry.all_items]

    return app


async def _labels(app: Any, path: str) -> list[str]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_mounted_childs_sidebar_shows_no_default_tenant_types(db_state):
    module = await _synced_module(db_state)
    child = _sidebar_app(module)
    parent = Starlette(routes=[Mount("/child", app=child)])

    assert await _labels(parent, "/child/admin/records/") == ["All record types"]
    # Latched: the registry is process-wide, so a later request served
    # directly must not put the entries back for the mounted tenants to see.
    assert await _labels(child, "/admin/records/") == ["All record types"]
    assert module._type_menu_items == []


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


async def test_an_unmounted_single_tenant_sidebar_keeps_its_types(db_state):
    module = await _synced_module(db_state)
    assert await _labels(_sidebar_app(module), "/admin/records/") == [
        "All record types",
        "Companies",
    ]
