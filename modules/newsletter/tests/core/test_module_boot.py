"""The skeleton's registrations: permissions, the locale directory, startup."""

from __future__ import annotations

from simple_module_core.permissions import PermissionRegistry
from sm_newsletter.core import constants
from sm_newsletter.module import NewsletterModule

EXPECTED_PERMISSIONS = {
    "newsletter.view",
    "newsletter.edit",
    "newsletter.send",
    "newsletter.manage",
}


def test_module_registers_permissions():
    registry = PermissionRegistry()
    NewsletterModule().register_permissions(registry)
    assert set(registry.all_permissions) == EXPECTED_PERMISSIONS
    (group,) = registry.groups
    assert group.name == constants.PERM_GROUP == "Newsletter"
    assert group.label_key == "newsletter.permission_group"
    # Settings are governed by the framework's ``settings.edit``.
    assert "newsletter.settings" not in registry.all_permissions


def test_locale_dir_is_the_namespace():
    dirs = NewsletterModule().locale_dirs()
    assert "newsletter" in dirs
    names = {p.name for p in dirs["newsletter"].iterdir()}
    assert {"en.json", "de.json"} <= names


async def test_on_startup_configures_tenancy_and_installs_the_guard(monkeypatch):
    from types import SimpleNamespace

    from sm_newsletter.core import tenancy

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(tenancy, "configure", lambda app: calls.append(("configure", app)))
    monkeypatch.setattr(tenancy, "install_guard", lambda cls: calls.append(("guard", cls)))
    session_class = object()
    app = SimpleNamespace(
        state=SimpleNamespace(
            sm=SimpleNamespace(db=SimpleNamespace(sync_session_class=session_class))
        )
    )
    await NewsletterModule().on_startup(app)
    assert calls == [("configure", app), ("guard", session_class)]

    calls.clear()
    bare = SimpleNamespace(state=SimpleNamespace())
    await NewsletterModule().on_startup(bare)
    assert calls == [("configure", bare)]
