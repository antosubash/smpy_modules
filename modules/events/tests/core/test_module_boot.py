"""The skeleton's registrations: permissions, the locale directory, metadata."""

from __future__ import annotations

from simple_module_core.permissions import PermissionRegistry
from sm_events.module import EventsModule

EXPECTED_PERMISSIONS = {"events.view", "events.edit", "events.publish", "events.manage"}


def test_module_registers_permissions():
    registry = PermissionRegistry()
    EventsModule().register_permissions(registry)
    assert set(registry.all_permissions) == EXPECTED_PERMISSIONS
    (group,) = registry.groups
    assert group.label_key == "events.permission_group"


def test_locale_dir_is_the_namespace():
    dirs = EventsModule().locale_dirs()
    assert "events" in dirs
    names = {p.name for p in dirs["events"].iterdir()}
    assert {"en.json", "de.json"} <= names


def test_meta():
    meta = EventsModule.meta
    assert meta.name == "Events"
    assert meta.route_prefix == "/api/events"
    assert meta.view_prefix == "/admin/events"
    assert set(meta.depends_on) == {"Settings", "Sharing", "BackgroundTasks"}


async def test_on_startup_configures_tenancy_and_installs_the_guard(monkeypatch):
    from types import SimpleNamespace

    from sm_events.core import tenancy

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(tenancy, "configure", lambda app: calls.append(("configure", app)))
    monkeypatch.setattr(tenancy, "install_guard", lambda cls: calls.append(("guard", cls)))
    session_class = object()
    app = SimpleNamespace(
        state=SimpleNamespace(
            sm=SimpleNamespace(db=SimpleNamespace(sync_session_class=session_class))
        )
    )
    await EventsModule().on_startup(app)
    assert calls == [("configure", app), ("guard", session_class)]

    calls.clear()
    bare = SimpleNamespace(state=SimpleNamespace())
    await EventsModule().on_startup(bare)
    assert calls == [("configure", bare)]


async def test_on_startup_installs_the_token_log_filter():
    import logging
    from types import SimpleNamespace

    from sm_events.feeds.tokens import log_redact

    for name in log_redact.LOGGERS:  # a clean slate: another test may have installed it
        target = logging.getLogger(name)
        target.filters = [f for f in target.filters if not isinstance(f, log_redact.Filter)]
    await EventsModule().on_startup(SimpleNamespace(state=SimpleNamespace()))
    for name in log_redact.LOGGERS:
        assert any(isinstance(f, log_redact.Filter) for f in logging.getLogger(name).filters), name


async def test_startup_freezes_registry():
    from types import SimpleNamespace

    from sm_events.calendar import registry

    registry.reset_registry()
    try:
        await EventsModule().on_startup(SimpleNamespace(state=SimpleNamespace()))
        assert registry.is_frozen()
        assert registry.builtin_source() is not None
    finally:
        registry.reset_registry()


def test_import_upload_body_limit_is_registered():
    from simple_module_core.body_limits import BodyLimitRegistry

    registry = BodyLimitRegistry()
    EventsModule().register_body_limits(registry)
    ceiling = 21 * 1024 * 1024
    for path in ("/api/events/imports", "/api/events/imports/"):
        assert registry.limit_for("POST", path) == ceiling
    assert registry.limit_for("GET", "/api/events/imports") is None
    assert registry.limit_for("POST", "/api/events/imports/1/apply") is None
    assert registry.limit_for("POST", "/api/events/calendars") is None
