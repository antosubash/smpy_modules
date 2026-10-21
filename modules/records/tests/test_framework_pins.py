"""Pins on the framework internals records reads (#125).

The module range admits any 0.0.x framework, but three call sites read names
the framework does not promise to keep. Each test here fails, with a message
naming the call site, the moment one of them changes — in CI on the
framework bump, not in production.

* ``sm_records/_tenancy_mode.py`` — ``TenantMiddleware``, its ``fixed`` /
  ``header`` keywords, Starlette's ``user_middleware`` entry shape. Public
  replacement (0.0.36+): ``simple_module_hosting.tenancy``.
* ``sm_records/menu.py`` (``sync_type_menu``) — ``MenuRegistry._items`` and
  ``_invalidate()``. Public replacement (core 0.0.36+): ``MenuRegistry.remove``.
* ``sm_records/endpoints/api/_errors.py`` —
  ``simple_module_hosting._error_handlers.render_error_page``. No public
  replacement yet.
"""

from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection
from sm_records import _tenancy_mode as tenancy
from sm_records import constants, menu
from sm_records.tenancy import TenancyMode

pytestmark = pytest.mark.unbound_tenant

_TENANCY = "sm_records/_tenancy_mode.py (_tenant_middleware / _kwargs)"
_MENU = "sm_records/menu.py (sync_type_menu)"
_ERRORS = "sm_records/endpoints/api/_errors.py (_error_page)"


# --- tenancy mode -------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(tenancy._KNOWN_KWARGS))
def test_tenant_middleware_still_takes_the_keywords_read(name):
    from simple_module_hosting.middleware import TenantMiddleware

    params = inspect.signature(TenantMiddleware.__init__).parameters
    assert name in params and params[name].kind is inspect.Parameter.KEYWORD_ONLY, (
        f"{_TENANCY}: TenantMiddleware.__init__ no longer takes keyword {name!r} "
        f"(has {list(params)}); mode detection reads it off the built stack"
    )


def test_starlette_middleware_entries_keep_cls_args_kwargs():
    from simple_module_hosting.middleware import TenantMiddleware

    app = FastAPI()
    app.add_middleware(TenantMiddleware, header="X-Tenant-ID")
    entries = getattr(app, "user_middleware", None)
    assert isinstance(entries, list), f"{_TENANCY}: app.user_middleware is gone"
    [entry] = entries
    assert entry.cls is TenantMiddleware, f"{_TENANCY}: user_middleware entries lost .cls"
    assert tuple(entry.args) == (), f"{_TENANCY}: user_middleware entries lost .args"
    assert dict(entry.kwargs) == {"header": "X-Tenant-ID"}, f"{_TENANCY}: entries lost .kwargs"


def _with_entry(**fields):
    from simple_module_hosting.middleware import TenantMiddleware

    app = FastAPI()
    app.user_middleware = [SimpleNamespace(cls=TenantMiddleware, **fields)]
    setattr(app.state, constants.PACKAGE, SimpleNamespace(tenancy=None))
    return app


@pytest.mark.parametrize(
    "fields",
    [
        {"args": (), "kwargs": {"pinned": "default"}},  # ``fixed`` renamed
        {"args": ("default",), "kwargs": {}},  # passed positionally
        {"args": ()},  # entries lost .kwargs
    ],
)
def test_unrecognised_arguments_are_multi_not_single(fields, caplog):
    app = _with_entry(**fields)
    assert tenancy.detect_mode(app) is TenancyMode.MULTI
    with caplog.at_level(logging.WARNING, logger="sm_records.tenancy"):
        assert tenancy.configure(app) is TenancyMode.MULTI
    assert "does not recognise" in caplog.text
    assert tenancy.tenant_header(app) is None


def test_a_subclassed_middleware_is_still_found():
    from simple_module_hosting.middleware import TenantMiddleware

    class Wrapped(TenantMiddleware):
        pass

    app = FastAPI()
    app.add_middleware(Wrapped, header="X-Tenant-ID")
    assert tenancy.detect_mode(app) is TenancyMode.MULTI
    assert tenancy.tenant_header(app) == "X-Tenant-ID"


def test_an_unreadable_stack_refuses_to_guess():
    app = FastAPI()
    app.user_middleware = [object()]  # entries without .cls
    with pytest.raises(RuntimeError, match="Refusing to guess"):
        tenancy.configure(app)


def test_the_frameworks_own_multi_wins():
    pytest.importorskip("simple_module_hosting.tenancy")
    app = FastAPI()  # no TenantMiddleware at all
    app.state.sm = SimpleNamespace(tenancy="multi")
    assert tenancy.detect_mode(app) is TenancyMode.MULTI


# --- menu registry ------------------------------------------------------------


def test_menu_registry_keeps_items_list_and_invalidate():
    registry = MenuRegistry()
    assert isinstance(getattr(registry, "_items", None), list), (
        f"{_MENU}: MenuRegistry._items is gone or no longer a list; the splice "
        "that removes stale per-type entries writes it in place"
    )
    assert callable(getattr(registry, "_invalidate", None)), (
        f"{_MENU}: MenuRegistry._invalidate() is gone; without it all_items "
        "keeps serving the sorted cache from before the splice"
    )


def test_the_splice_reaches_all_items():
    """Behaviour, not just names: a removed entry leaves the *sorted* view."""
    registry = MenuRegistry()
    hub = MenuItem(label="Hub", url="/hub", order=1, section=MenuSection.ADMIN_SIDEBAR)
    registry.add(hub)
    [ours] = menu.sync_type_menu(registry, [menu.MenuType("a", "As", None, [])])
    assert ours in registry.all_items  # warms the sorted cache
    menu.sync_type_menu(registry, [], previous=[ours])
    assert registry.all_items == [hub], (
        f"{_MENU}: removing through _items/_invalidate no longer changes all_items"
    )


# --- error page ---------------------------------------------------------------


def test_render_error_page_keeps_its_name_and_signature():
    try:
        from simple_module_hosting._error_handlers import render_error_page
    except ImportError as exc:
        pytest.fail(
            f"{_ERRORS}: simple_module_hosting._error_handlers.render_error_page is gone "
            f"({exc}); view routes would fall back to JSON instead of the error page"
        )
    assert inspect.iscoroutinefunction(render_error_page), f"{_ERRORS}: no longer async"
    params = list(inspect.signature(render_error_page).parameters)
    assert params[:3] == ["request", "status_code", "message"], (
        f"{_ERRORS}: render_error_page(request, status, detail) no longer fits: {params}"
    )
