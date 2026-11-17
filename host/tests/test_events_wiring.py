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
