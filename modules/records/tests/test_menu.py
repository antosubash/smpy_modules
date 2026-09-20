"""The per-type sidebar entries: what they look like, and when they are read.

Three layers, tested at three levels, because they fail differently.

:func:`~sm_records.menu.type_menu_items` is pure — label, url, icon fallback,
roles and the alphabetical order the registry's ``order``-only sort leaves to
insertion. :func:`~sm_records.menu.sync_type_menu` is the one place this module
reaches inside the framework's registry, so what it must never do (touch an
item it did not put there) is asserted directly against ``all_items``. And
:func:`~sm_records.menu.refresh` is about *timing*: the TTL, the dirty flag a
type write sets, and the read that fails without taking the request with it.
"""

from __future__ import annotations

from typing import Any

import pytest
from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection
from sm_records import constants, menu
from sm_records.menu import MenuType
from sm_records.module import RecordsModule
from sm_records.settings import RecordsSettings

from tests.app_harness import seed_type


def _type(key: str, plural: str, *, icon: str | None = None, roles: list[str] | None = None):
    return MenuType(key=key, label_plural=plural, icon=icon, allowed_roles=roles or [])


def _hub() -> MenuItem:
    """The module's own "Records" entry, as ``register_menu_items`` adds it."""
    return MenuItem(
        label="Records",
        url=constants.MENU_URL,
        icon=constants.MENU_ICON,
        order=constants.MENU_ORDER,
        section=MenuSection.ADMIN_SIDEBAR,
        group=constants.MENU_GROUP,
    )


def test_item_carries_the_types_label_url_icon_and_roles():
    [item] = menu.type_menu_items([_type("company", "Companies", icon="building", roles=["ops"])])

    assert item.label == "Companies"
    assert item.url == f"{constants.VIEW_PREFIX}/company"
    assert item.icon == "building"
    assert item.roles == ["ops"]
    assert item.section is MenuSection.ADMIN_SIDEBAR
    assert item.group == constants.MENU_GROUP
    # One past the hub, so the types cluster directly under it.
    assert item.order == constants.MENU_ORDER + 1


def test_item_without_an_icon_falls_back_to_the_modules_own():
    [item] = menu.type_menu_items([_type("order", "Orders")])

    assert item.icon == constants.MENU_ICON
    # Empty roles is the registry's "every authenticated user", not "nobody".
    assert item.roles == []


def test_items_are_inserted_in_case_insensitive_alphabetical_order():
    items = menu.type_menu_items(
        [_type("z", "zebras"), _type("c", "Companies"), _type("a", "apples")]
    )

    # The registry sorts by ``order`` alone and stably, so this insertion order
    # is the order the sidebar renders in.
    assert [item.label for item in items] == ["apples", "Companies", "zebras"]


def test_sync_adds_items_and_leaves_foreign_ones_alone():
    registry = MenuRegistry()
    hub = _hub()
    host_item = MenuItem(label="Reports", url=f"{constants.VIEW_PREFIX}/reports", order=10)
    registry.add_many([hub, host_item])

    ours = menu.sync_type_menu(registry, [_type("company", "Companies")])

    assert [item.label for item in registry.all_items] == ["Reports", "Records", "Companies"]
    assert [item.label for item in ours] == ["Companies"]


def test_sync_replaces_only_the_items_it_added_last_time():
    registry = MenuRegistry()
    host_item = MenuItem(label="Reports", url=f"{constants.VIEW_PREFIX}/reports", order=10)
    registry.add_many([_hub(), host_item])
    ours = menu.sync_type_menu(registry, [_type("company", "Companies")])

    # ``company`` renamed, ``order`` newly opted in.
    ours = menu.sync_type_menu(
        registry, [_type("company", "Firms"), _type("order", "Orders")], previous=ours
    )

    labels = [item.label for item in registry.all_items]
    assert labels == ["Reports", "Records", "Firms", "Orders"]
    assert "Companies" not in labels
    assert [item.label for item in ours] == ["Firms", "Orders"]


def test_sync_with_nothing_opted_in_removes_our_items_and_keeps_the_hub():
    registry = MenuRegistry()
    registry.add(_hub())
    ours = menu.sync_type_menu(registry, [_type("company", "Companies")])

    ours = menu.sync_type_menu(registry, [], previous=ours)

    assert [item.label for item in registry.all_items] == ["Records"]
    assert ours == []


def test_sync_that_changes_nothing_does_not_touch_the_registry():
    registry = MenuRegistry()
    registry.add(_hub())
    ours = menu.sync_type_menu(registry, [_type("company", "Companies")])
    before = [id(item) for item in registry.all_items]

    ours = menu.sync_type_menu(registry, [_type("company", "Companies")], previous=ours)

    assert [id(item) for item in registry.all_items] == before


def test_sync_keeps_a_host_item_that_looks_exactly_like_ours():
    """Removal is by identity, not by value: a host that adds the same entry
    by hand keeps it, however indistinguishable the two items are."""
    registry = MenuRegistry()
    ours = menu.sync_type_menu(registry, [_type("company", "Companies")])
    registry.add(menu.type_menu_items([_type("company", "Companies")])[0])

    menu.sync_type_menu(registry, [], previous=ours)

    assert [item.label for item in registry.all_items] == ["Companies"]


async def test_load_menu_types_reads_only_the_types_that_asked(db_state):
    await seed_type(db_state, "company", [], label_plural="Companies", show_in_menu=True)
    await seed_type(db_state, "secret", [], label_plural="Secrets")
    await seed_type(
        db_state, "order", [], label_plural="Orders", show_in_menu=True, allowed_roles=["ops"]
    )

    loaded = await menu.load_menu_types(db_state)

    assert [mt.key for mt in loaded] == ["company", "order"]
    assert loaded[1].allowed_roles == ["ops"]


def _module(db_state: Any, **settings: Any) -> RecordsModule:
    """A module instance wired the way ``on_startup`` leaves one."""
    module = RecordsModule()
    module.settings = RecordsSettings(**settings)
    module.db = db_state
    module.menu_registry = MenuRegistry()
    module.menu_registry.add(_hub())
    return module


async def test_refresh_does_nothing_without_a_registry(db_state):
    module = _module(db_state)
    module.menu_registry = None

    assert await menu.refresh(module, force=True) is False


async def test_refresh_honours_the_window_and_the_dirty_flag(db_state):
    await seed_type(db_state, "company", [], label_plural="Companies", show_in_menu=True)
    module = _module(db_state, menu_refresh_seconds=300)

    assert await menu.refresh(module, force=True) is True
    assert [item.label for item in module.menu_registry.all_items] == ["Records", "Companies"]

    # Inside the window, and nothing said otherwise.
    await seed_type(db_state, "order", [], label_plural="Orders", show_in_menu=True)
    assert await menu.refresh(module) is False
    assert [item.label for item in module.menu_registry.all_items] == ["Records", "Companies"]

    # What a type write in this process does — the endpoints call it through
    # ``menu.mark_dirty``.
    module.mark_menu_dirty()
    assert await menu.refresh(module) is True
    assert [item.label for item in module.menu_registry.all_items] == [
        "Records",
        "Companies",
        "Orders",
    ]


async def test_refresh_with_a_zero_window_reads_every_time(db_state):
    module = _module(db_state, menu_refresh_seconds=0)

    assert await menu.refresh(module) is True
    assert await menu.refresh(module) is True


async def test_a_failed_read_keeps_the_previous_items(db_state, caplog):
    await seed_type(db_state, "company", [], label_plural="Companies", show_in_menu=True)
    module = _module(db_state, menu_refresh_seconds=0)
    await menu.refresh(module)

    class _Broken:
        def session_factory(self):
            raise RuntimeError("no such table: records_type")

    module.db = _Broken()
    with caplog.at_level("WARNING"):
        assert await menu.refresh(module) is False

    assert [item.label for item in module.menu_registry.all_items] == ["Records", "Companies"]
    assert "sidebar" in caplog.text


def test_affects_menu_only_for_columns_an_entry_is_built_from():
    assert menu.affects_menu({"label_plural": "Firms"})
    assert menu.affects_menu({"show_in_menu": True})
    assert menu.affects_menu({"icon": "building"})
    assert menu.affects_menu({"allowed_roles": ["ops"]})
    assert not menu.affects_menu({"label": "Firm", "description": "x", "fields_raw": []})
    assert not menu.affects_menu({})


async def test_middleware_skips_the_paths_that_render_no_sidebar(db_state, monkeypatch):
    from sm_records._menu_middleware import MenuSyncMiddleware

    synced: list[bool] = []

    async def _fake_refresh(module, *, force=False):
        synced.append(force)
        return True

    monkeypatch.setattr(menu, "refresh", _fake_refresh)
    seen: list[str] = []

    async def _inner(scope, receive, send):
        seen.append(scope["path"])

    middleware = MenuSyncMiddleware(_inner, module=_module(db_state))

    for path in ("/api/records/types", "/static/app.css", "/health/ready"):
        await middleware({"type": "http", "path": path}, _receive, _send)
    assert synced == []

    await middleware({"type": "http", "path": "/admin/records/"}, _receive, _send)
    assert synced == [False]
    # Every one of them still reached the app — skipping the sync is not
    # skipping the request.
    assert len(seen) == 4


@pytest.mark.parametrize("scope_type", ["websocket", "lifespan"])
async def test_middleware_passes_non_http_scopes_straight_through(db_state, scope_type):
    from sm_records._menu_middleware import MenuSyncMiddleware

    seen: list[dict] = []

    async def _inner(scope, receive, send):
        seen.append(scope)

    middleware = MenuSyncMiddleware(_inner, module=_module(db_state))
    await middleware({"type": scope_type}, _receive, _send)

    assert seen == [{"type": scope_type}]


async def _receive() -> dict:
    return {"type": "http.request"}


async def _send(message: dict) -> None:
    return None
