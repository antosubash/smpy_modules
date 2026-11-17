"""The host mounts events and its tables reach the migration metadata."""

from __future__ import annotations

from simple_module_db import build_module_metadata
from simple_module_hosting import Settings, create_app

EVENTS_TABLES = {
    "events_calendar",
    "events_event",
    "events_event_text",
    "events_occurrence_override",
    "events_category",
    "events_revision",
    "events_redirect",
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
        "/admin/events/list",
        "/admin/events/edit/new",
        "/admin/events/edit/{event_id}",
    }
    items = [i for i in app.state.sm.menu_registry.all_items if i.group == "Events"]
    assert {i.url for i in items} == {
        "/admin/events/list",
        "/admin/events/calendars",
        "/admin/events/categories",
    }
    assert min(items, key=lambda i: i.order).url == "/admin/events/list"
    assert {i.url: i.permissions for i in items} == {
        "/admin/events/list": ["events.view"],
        "/admin/events/calendars": ["events.view"],
        "/admin/events/categories": ["events.view", "events.manage"],
    }


def test_resource_type_and_middleware():
    from sm_events.core.tenancy.request_context import RequestContextMiddleware

    app = create_app(Settings())
    assert app.state.sm.resource_types.get("events.calendar") is not None
    assert RequestContextMiddleware in {m.cls for m in app.user_middleware}
