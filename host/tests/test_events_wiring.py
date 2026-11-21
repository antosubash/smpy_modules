"""The host mounts events and its tables reach the migration metadata."""

from __future__ import annotations

import sys
from pathlib import Path

from simple_module_db import build_module_metadata
from simple_module_hosting import Settings, create_app

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "host"))

# What ``main.py`` imports before ``create_app``: the records module seals its collection
# registry in the first app any test builds.
import records_collections  # noqa: E402, F401

EVENTS_TABLES = {
    "events_calendar",
    "events_event",
    "events_event_text",
    "events_occurrence_override",
    "events_category",
    "events_revision",
    "events_redirect",
    "events_calendar_redirect",
    "events_feed_token",
    "events_import",
    "events_import_item",
    "events_follow",
    "events_reminder_sent",
    "events_registration_count",
    "events_registration_seat",
    "events_subscription",
    "events_fetch_target",
    "events_external_item",
}


def test_host_metadata_has_events_tables():
    tables = set(build_module_metadata().tables)
    assert {t for t in tables if t.startswith("events_")} == EVENTS_TABLES


def test_host_loads_the_module():
    app = create_app(Settings())
    names = {m.meta.name for m in app.state.sm.modules}
    assert "Events" in names


def test_views_and_menu_mounted():
    from fastapi.routing import iter_route_contexts

    app = create_app(Settings())
    paths = {ctx.path for ctx in iter_route_contexts(app.routes)}
    assert paths >= {
        "/admin/events/",
        "/admin/events/calendars",
        "/admin/events/categories",
        "/admin/events/import",
        "/admin/events/list",
        "/admin/events/reminders",
        "/admin/events/edit/new",
        "/admin/events/edit/{event_id}",
    }
    items = [i for i in app.state.sm.menu_registry.all_items if i.group == "Events"]
    assert {i.url for i in items} == {
        "/admin/events/",
        "/admin/events/list",
        "/admin/events/calendars",
        "/admin/events/categories",
        "/admin/events/import",
        "/admin/events/reminders",
    }
    assert min(items, key=lambda i: i.order).url == "/admin/events/"
    assert {i.url: i.permissions for i in items} == {
        "/admin/events/": ["events.view"],
        "/admin/events/list": ["events.view"],
        "/admin/events/calendars": ["events.view"],
        "/admin/events/categories": ["events.view", "events.manage"],
        "/admin/events/import": ["events.view", "events.manage"],
        "/admin/events/reminders": ["events.view"],
    }


def test_resource_type_and_middleware():
    from sm_events.core.tenancy.request_context import RequestContextMiddleware

    app = create_app(Settings())
    assert app.state.sm.resource_types.get("events.calendar") is not None
    assert RequestContextMiddleware in {m.cls for m in app.user_middleware}
