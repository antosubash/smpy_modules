"""Pins on the framework internals records reads (#125).

The module range admits any 0.0.x framework, but two call sites read names
the framework does not promise to keep. Each test here fails, with a message
naming the call site, the moment one of them changes — in CI on the
framework bump, not in production.

* ``sm_records/_tenancy_mode.py`` — ``TenantMiddleware``, its ``fixed`` /
  ``header`` keywords, Starlette's ``user_middleware`` entry shape. Since the
  0.0.36 floor (#211) the framework's public ``tenancy_mode`` and
  ``single_tenant_id`` come first; the stack stays the fallback for an app
  built outside ``create_app`` and the source of the tenant header, which
  has no public replacement yet.
* ``sm_records/menu.py`` and ``sm_records/type_permissions.py`` —
  ``MenuRegistry.add_provider`` and ``PermissionRegistry.add_source`` /
  ``invalidate_source`` (0.0.36, upstream #340 / #334). Public, but the
  sidebar and the role editor rest on how they behave, so that is pinned.
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
_MENU = "sm_records/menu.py (type_menu_provider)"
_PERMS = "sm_records/type_permissions.py (TypePermissions)"
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
    app = FastAPI()  # no TenantMiddleware at all
    app.state.sm = SimpleNamespace(tenancy="multi")
    assert tenancy.detect_mode(app) is TenancyMode.MULTI


def _create_app_host(default_tenant_id):
    app = FastAPI()
    app.state.sm = SimpleNamespace(
        tenancy="single", db=SimpleNamespace(default_tenant_id=default_tenant_id)
    )
    setattr(app.state, constants.PACKAGE, SimpleNamespace(tenancy=None))
    return app


def test_a_create_app_hosts_pinned_tenant_is_the_frameworks_answer():
    """``single_tenant_id``, not the stack: no ``TenantMiddleware`` here."""
    assert tenancy.configure(_create_app_host(None)) is TenancyMode.SINGLE
    with pytest.raises(RuntimeError, match="default_tenant='acme'"):
        tenancy.configure(_create_app_host("acme"))


def test_an_explicit_fixed_pin_must_agree_with_the_frameworks_answer():
    """``single_tenant_id`` says ``"default"`` but the stack pins ``"acme"``:
    requests would follow the middleware and background work the framework,
    so startup refuses the split (#212)."""
    from simple_module_hosting.middleware import TenantMiddleware

    split = _create_app_host(None)
    split.add_middleware(TenantMiddleware, fixed="acme")
    with pytest.raises(RuntimeError, match=r"TenantMiddleware\(fixed='acme'\)") as refused:
        tenancy.configure(split)
    assert "default_tenant=" not in str(refused.value)  # the framework's pin is fine
    agreeing = _create_app_host(None)
    agreeing.add_middleware(TenantMiddleware, fixed="default")
    assert tenancy.configure(agreeing) is TenancyMode.SINGLE


# --- menu registry ------------------------------------------------------------


async def test_a_provider_reaches_the_rendered_sidebar():
    """Behaviour, not just names: ``get_for_request`` asks the provider with
    the request and renders its items after the static ones of equal order."""
    registry = MenuRegistry()
    hub = MenuItem(label="Hub", url="/hub", order=1, section=MenuSection.ADMIN_SIDEBAR)
    registry.add(hub)
    seen: list[object] = []

    async def provider(request):
        seen.append(request)
        return menu.type_menu_items([menu.MenuType("a", "As", None, [])])

    registry.add_provider(provider)
    request = object()
    rendered = await registry.get_for_request(request, is_authenticated=True)  # type: ignore[arg-type]
    assert seen == [request], f"{_MENU}: MenuRegistry no longer passes the request to a provider"
    labels = [entry["label"] for entry in rendered[MenuSection.ADMIN_SIDEBAR.value]]
    assert labels == ["Hub", "As"], f"{_MENU}: provider items no longer render after the hub"


def test_a_permission_source_reaches_the_role_editor():
    """``add_source`` keys join the group of the same name, with their labels,
    and ``invalidate_source`` makes the registry ask again."""
    from simple_module_core.permissions import PermissionRegistry

    registry = PermissionRegistry()
    registry.add_group(constants.PERM_GROUP, [constants.PERM_VIEW])
    entries = [("records.type.a", "Records: As")]
    registry.add_source(constants.PERM_GROUP, lambda: list(entries))
    [group] = registry.groups
    assert group.permissions == [constants.PERM_VIEW, "records.type.a"], f"{_PERMS}: merge changed"
    assert registry.source_labels(constants.PERM_GROUP) == {"records.type.a": "Records: As"}
    entries.append(("records.type.b", "Records: Bs"))
    assert "records.type.b" not in registry.all_permissions, f"{_PERMS}: source no longer cached"
    registry.invalidate_source(constants.PERM_GROUP)
    assert "records.type.b" in registry.all_permissions, f"{_PERMS}: invalidate_source is inert"


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


# --- no shared or premature cache ---------------------------------------------


def test_each_app_keeps_its_own_mode():
    """The mode lives on the app it was read from — nothing module-level."""
    from simple_module_hosting.middleware import TenantMiddleware

    single, multi = FastAPI(), FastAPI()
    multi.add_middleware(TenantMiddleware, header="X-Tenant-ID")
    setattr(single.state, constants.PACKAGE, SimpleNamespace(tenancy=None))
    setattr(multi.state, constants.PACKAGE, SimpleNamespace(tenancy=None))
    assert tenancy.configure(single) is TenancyMode.SINGLE
    assert tenancy.configure(multi) is TenancyMode.MULTI
    assert tenancy.mode_of(single) is TenancyMode.SINGLE
    assert tenancy.mode_of(multi) is TenancyMode.MULTI


def test_a_detection_before_the_middleware_is_added_does_not_stick():
    from simple_module_hosting.middleware import TenantMiddleware

    app = FastAPI()
    assert tenancy.mode_of(app) is TenancyMode.SINGLE  # nothing stored by this
    app.add_middleware(TenantMiddleware)
    assert tenancy.mode_of(app) is TenancyMode.MULTI
