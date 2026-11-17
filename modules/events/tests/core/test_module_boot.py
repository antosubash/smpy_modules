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
    assert set(meta.depends_on) == {"Settings", "Sharing"}
