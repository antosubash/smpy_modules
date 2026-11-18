"""The built-in source and type go through the same registry as a plugin's."""

from __future__ import annotations

import pytest
from sm_events.calendar import registry
from sm_events.calendar.extension_types import NoExtra
from sm_events.calendar.sources import EVENTS_SOURCE

from tests.calendar.test_occurrences import OWNER, read, utc
from tests.support.access import seed_calendars
from tests.support.calendars import seed_event, seed_series


@pytest.fixture(autouse=True)
def _fresh_registry():
    registry.reset_registry()
    yield
    registry.reset_registry()


def test_builtins_registered():
    assert registry.builtin_source() is EVENTS_SOURCE
    assert registry.get_type("event").extra_model is NoExtra  # type: ignore[union-attr]
    assert registry.is_frozen()


def test_builtin_not_in_plugin_sources():
    assert registry.plugin_sources() == {}
    assert registry.get_source("events") is None
    assert list(registry.all_types()) == ["event"]


def test_builtin_source_has_the_plugin_attributes():
    assert EVENTS_SOURCE.public is True
    assert EVENTS_SOURCE.settings_model is None
    assert EVENTS_SOURCE.label_key and EVENTS_SOURCE.icon


async def test_read_unchanged(db):
    cals = await seed_calendars(db)
    cal = cals["I"]
    await seed_event(db, cal, title="late", status="published", starts_at=utc(2026, 7, 8, 12))
    await seed_event(db, cal, title="early", status="published", starts_at=utc(2026, 7, 6, 6))
    await seed_series(
        db,
        cal,
        "FREQ=WEEKLY;BYDAY=MO",
        "2026-07-06T10:00",
        "2026-07-06T11:00",
        title="weekly",
        status="published",
    )
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 20))
    assert [(o.title, o.start) for o in page.items] == [
        ("early", utc(2026, 7, 6, 6)),
        ("weekly", utc(2026, 7, 6, 8)),
        ("late", utc(2026, 7, 8, 12)),
        ("weekly", utc(2026, 7, 13, 8)),
    ]
    assert registry.is_frozen()  # the read loaded the registry, as a worker's first read does
