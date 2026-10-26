"""The per-type sidebar entries: what they look like, who sees them, and when
they are read.

:func:`~sm_records.menu.type_menu_items` is pure — label, url, icon fallback
and the alphabetical order the registry's ``order``-only sort leaves to the
provider. :func:`~sm_records.menu.visible_items` is the per-caller filter.
:func:`~sm_records.menu.type_menu_provider` is what the framework calls per
request (upstream #340): the tenant it reads, the paths it never reads on,
the cache it keeps per tenant, and the read that fails without taking the
page with it. Per-tenant behaviour over HTTP is ``test_menu_tenancy.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from simple_module_core.menu import MenuRegistry, MenuSection
from sm_records import constants, menu
from sm_records.menu import MenuType
from sm_records.module import RecordsModule
from sm_records.settings import RecordsSettings
from sm_records.tenancy import TenancyMode, tenant_scope
from starlette.requests import Request

from tests.app_harness import seed_type

_VIEW = {constants.PERM_VIEW}


def _type(key: str, plural: str, *, icon: str | None = None, roles: list[str] | None = None):
    return MenuType(key=key, label_plural=plural, icon=icon, allowed_roles=roles or [])


def _user(*roles: str) -> SimpleNamespace:
    return SimpleNamespace(id="u", roles=list(roles))


def test_item_carries_the_types_label_url_and_icon_and_no_roles():
    [item] = menu.type_menu_items([_type("company", "Companies", icon="building", roles=["ops"])])

    assert item.label == "Companies"
    assert item.url == f"{constants.VIEW_PREFIX}/company"
    assert item.icon == "building"
    # Visibility is decided per caller by ``visible_items``, not by the
    # registry's role filter, which cannot see a per-type grant.
    assert item.roles == []
    assert item.section is MenuSection.ADMIN_SIDEBAR
    assert item.group == constants.MENU_GROUP_TYPES
    assert item.order == constants.MENU_ORDER + 1


def test_item_without_an_icon_falls_back_to_the_modules_own():
    [item] = menu.type_menu_items([_type("order", "Orders")])
    assert item.icon == constants.MENU_ICON


def test_items_sort_by_plural_label_case_folded():
    items = menu.type_menu_items(
        [_type("z", "zebras"), _type("a", "Apples"), _type("m", "mangoes"), _type("b", "Bananas")]
    )
    assert [item.label for item in items] == ["Apples", "Bananas", "mangoes", "zebras"]


def test_visible_items_follow_allowed_roles_with_no_admin_exception():
    types = [_type("open", "Opens"), _type("ops", "Ops things", roles=["ops"])]

    assert [i.label for i in menu.visible_items(types, _user("ops"), _VIEW)] == [
        "Opens",
        "Ops things",
    ]
    assert [i.label for i in menu.visible_items(types, _user("sales"), _VIEW)] == ["Opens"]
    # The wildcard reaches ``records.view`` but not a narrowed type.
    assert [i.label for i in menu.visible_items(types, _user("admin"), {"*"})] == ["Opens"]


def test_a_per_type_grant_shows_a_narrowed_entry():
    types = [_type("ops", "Ops things", roles=["ops"])]
    held = {constants.PERM_VIEW, "records.type.ops"}
    assert [i.label for i in menu.visible_items(types, _user("sales"), held)] == ["Ops things"]
    # Another type's grant does nothing for this one.
    other = {constants.PERM_VIEW, "records.type.company"}
    assert menu.visible_items(types, _user("sales"), other) == []


def test_no_entries_without_records_view_or_without_a_user():
    types = [_type("open", "Opens")]
    assert menu.visible_items(types, _user("guest"), set()) == []
    assert menu.visible_items(types, None, _VIEW) == []


async def test_load_menu_types_reads_only_the_types_that_asked(db_state):
    await seed_type(db_state, "company", [], label_plural="Companies", show_in_menu=True)
    await seed_type(db_state, "secret", [], label_plural="Secrets")
    await seed_type(
        db_state, "order", [], label_plural="Orders", show_in_menu=True, allowed_roles=["ops"]
    )

    loaded = await menu.load_menu_types(db_state)

    assert [mt.key for mt in loaded] == ["company", "order"]
    assert loaded[1].allowed_roles == ["ops"]


# --- the provider -------------------------------------------------------------


def _module(db_state: Any, **settings: Any) -> RecordsModule:
    module = RecordsModule()
    module.settings = RecordsSettings(**settings)
    module.db = db_state
    module.tenancy_mode = TenancyMode.SINGLE
    return module


def _request(
    path: str = "/admin/records/",
    *,
    user: Any = None,
    held: set[str] | None = None,
    tenant: str | None = None,
    mode: TenancyMode = TenancyMode.SINGLE,
) -> Request:
    app = FastAPI()
    setattr(app.state, constants.PACKAGE, SimpleNamespace(tenancy=mode))
    state = {"user": user, "tenant_id": tenant, "resolved_permissions": held or set()}
    return Request({"type": "http", "path": path, "app": app, "state": state, "headers": []})


async def _labels(module: RecordsModule, **kwargs: Any) -> list[str]:
    return [item.label for item in await menu.type_menu_provider(module, _request(**kwargs))]


async def test_the_provider_lists_the_single_tenant_hosts_types(db_state):
    await seed_type(db_state, "company", [], label_plural="Companies", show_in_menu=True)
    module = _module(db_state)

    assert await _labels(module, user=_user("viewer"), held=_VIEW) == ["Companies"]


async def test_the_provider_reads_nothing_where_no_sidebar_renders(db_state):
    class _Unreadable:
        def session_factory(self):  # pragma: no cover - must never be called
            raise AssertionError("read on a path that renders no sidebar")

    module = _module(_Unreadable())
    for path in ("/api/records/types", "/static/app.css", "/health/ready"):
        assert await _labels(module, path=path, user=_user("v"), held=_VIEW) == []
    # Anonymous: nothing either, and no read.
    assert await _labels(module) == []


@pytest.mark.unbound_tenant
async def test_a_multi_tenant_request_with_no_tenant_gets_no_entries(db_state):
    with tenant_scope("default"):
        await seed_type(db_state, "company", [], label_plural="Companies", show_in_menu=True)
    module = _module(db_state)
    module.tenancy_mode = TenancyMode.MULTI

    assert await _labels(module, user=_user("v"), held=_VIEW, mode=TenancyMode.MULTI) == []


async def test_the_cache_honours_the_window_and_a_type_write(db_state):
    await seed_type(db_state, "company", [], label_plural="Companies", show_in_menu=True)
    module = _module(db_state, menu_refresh_seconds=300)
    ask = {"user": _user("v"), "held": _VIEW}

    assert await _labels(module, **ask) == ["Companies"]
    await seed_type(db_state, "order", [], label_plural="Orders", show_in_menu=True)
    assert await _labels(module, **ask) == ["Companies"], "inside the window"

    module.mark_menu_dirty()  # what a type write in this process does
    assert await _labels(module, **ask) == ["Companies", "Orders"]


async def test_a_zero_window_reads_every_time(db_state):
    module = _module(db_state, menu_refresh_seconds=0)
    ask = {"user": _user("v"), "held": _VIEW}
    assert await _labels(module, **ask) == []
    await seed_type(db_state, "company", [], label_plural="Companies", show_in_menu=True)
    assert await _labels(module, **ask) == ["Companies"]


async def test_a_failed_read_contributes_nothing_and_logs(caplog):
    class _Broken:
        def session_factory(self):
            raise RuntimeError("no such table: records_type")

    module = _module(_Broken(), menu_refresh_seconds=0)
    with caplog.at_level("WARNING"):
        assert await _labels(module, user=_user("v"), held=_VIEW) == []
    assert "sidebar" in caplog.text


def test_the_tenant_cache_never_answers_for_another_tenant():
    cache = menu.TypeMenuCache()
    cache.put("acme", [_type("secret", "Secrets")])
    assert cache.get("globex", 300) is None
    assert [t.key for t in cache.get("acme", 300) or []] == ["secret"]


def test_the_tenant_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(menu, "MAX_CACHED_TENANTS", 2)
    cache = menu.TypeMenuCache()
    for tenant in ("a", "b", "c"):
        cache.put(tenant, [])
    assert cache.get("a", 300) is None
    assert cache.get("c", 300) == []


async def test_register_menu_items_adds_the_hub_and_one_provider():
    module = RecordsModule()
    registry = MenuRegistry()
    module.register_menu_items(registry)

    assert [item.label for item in registry.all_items] == ["All record types"]
    # Before startup there is no database: the provider contributes nothing.
    assert await registry.collect_provider_items(_request(user=_user("v"), held=_VIEW)) == []


def test_affects_menu_only_for_columns_an_entry_is_built_from():
    assert menu.affects_menu({"label_plural": "Firms"})
    assert menu.affects_menu({"show_in_menu": True})
    assert menu.affects_menu({"icon": "building"})
    assert menu.affects_menu({"allowed_roles": ["ops"]})
    assert not menu.affects_menu({"label": "Firm", "description": "x", "fields_raw": []})
    assert not menu.affects_menu({})
