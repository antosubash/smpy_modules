"""Every sidebar entry this repo's modules contribute is translatable.

The framework translates ``label_key``/``group_key`` on the server and falls
back to the literal ``label``/``group`` when a key resolves to nothing — so a
missing key never breaks anything, it just leaves one entry English in an
otherwise German console. Only a test that boots the real host and asks the
registry for German notices that.
"""

from __future__ import annotations

import pytest
from simple_module_core.i18n import Translator
from simple_module_core.menu import MenuItem, MenuRegistry
from simple_module_hosting import Settings, create_app
from starlette.requests import Request

# This repo's modules, by the package that defines them — the framework's own
# entries (Users, Settings, …) are its business, not this test's.
_OUR_PACKAGES = {"pagebuilder", "news", "sm_records", "sm_ai", "sm_billing", "sm_images"}
_OUR_NAMESPACES = ("pagebuilder.", "news.", "records.", "ai.", "billing.", "images.")


@pytest.fixture(scope="module")
def app():
    return create_app(Settings(i18n_supported_locales=["en", "de"]))


def _admin_request() -> Request:
    """A request as the layout middleware leaves it for an admin: every permission."""
    return Request({"type": "http", "state": {"user": object(), "resolved_permissions": {"*"}}})


async def _ours(app) -> list[MenuItem]:
    """Ask our modules for their entries again, into a registry of their own.

    Per-request providers included (pagebuilder's Import / Export is one),
    evaluated for an admin.
    """
    registry = MenuRegistry()
    for module in app.state.sm.modules:
        if type(module).__module__.split(".")[0] in _OUR_PACKAGES:
            module.register_menu_items(registry)
    return [*registry.all_items, *await registry.collect_provider_items(_admin_request())]


async def _menu(app, locale: str) -> list[dict]:
    """The sidebar as the framework ships it to an admin in ``locale``."""
    translator = Translator(app.state.sm.i18n_registry, locale=locale, default_locale="en")
    menus = await app.state.sm.menu_registry.get_for_request(
        _admin_request(),
        is_authenticated=True,
        roles=["admin"],
        permissions=sorted({p for i in await _ours(app) for p in i.permissions}),
        translate=translator.t,
    )
    return [entry for entries in menus.values() for entry in entries]


async def test_every_entry_has_a_label_key(app):
    items = await _ours(app)
    assert len(items) == 13
    missing = [i.label for i in items if not i.label_key.startswith(_OUR_NAMESPACES)]
    assert not missing, f"menu items without a module label_key: {missing}"
    no_group_key = [i.label for i in items if i.group and not i.group_key]
    assert not no_group_key, f"grouped menu items without a group_key: {no_group_key}"


async def test_every_key_resolves(app):
    """A key with no catalogue entry would silently ship the English literal."""
    t = Translator(app.state.sm.i18n_registry, locale="de", default_locale="en").t
    keys = {k for i in await _ours(app) for k in (i.label_key, i.group_key) if k}
    assert {k for k in keys if t(k) == k} == set()


async def test_german_sidebar(app):
    menu = await _menu(app, "de")
    labels = {(e["url"], e["label"]) for e in menu}
    assert ("/pagebuilder/", "Seiten") in labels
    assert ("/pagebuilder/media", "Mediathek") in labels
    assert ("/pagebuilder/content", "Import / Export") in labels
    assert ("/admin/news/", "Artikel") in labels
    assert ("/ai/", "KI") in labels
    assert ("/admin/images/", "Bildersammlungen") in labels
    assert {"Website", "Datensätze", "Zugriff", "Bilder"} <= {e["group"] for e in menu}


async def test_english_sidebar_is_unchanged(app):
    """The en catalogue's values are the literals the items already carried."""
    shipped = {(e["url"], e["label"], e["group"]) for e in await _menu(app, "en")}
    assert {(i.url, i.label, i.group) for i in await _ours(app)} <= shipped
