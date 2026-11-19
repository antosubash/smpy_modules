"""The importer next to typed events and plugin sources: it never gives or takes a type."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sm_events.calendar.plugins import registry
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds import ics_calendar
from sm_events.feeds.select import feed_events
from sm_events.models import Calendar, Event
from sqlalchemy import select

from tests.feeds.importing import corpus
from tests.feeds.importing.runner_support import PUBLISHER, queue, read, run
from tests.feeds.importing.staging_support import make_import, seed
from tests.support.calendars import seed_event
from tests.support.sources import FakeSource, install, item, ok

NOW = datetime(2026, 6, 1, tzinfo=UTC)
RAW = {"b": 1, "a": [1, 2], "nested": {"z": None, "y": "ü"}}
GONE = "gone:thing"


@pytest.fixture(autouse=True)
def _registry():
    yield
    registry.reset_registry()


async def _export(db, cal) -> bytes:
    read_ = await feed_events(
        db,
        calendar_id=cal.id,
        locale="en",
        default_locale="en",
        now=NOW,
        url_for=lambda slug, loc: f"https://example.org/{slug}",
        events=select(Event).where(Event.tenant_id == "default"),
    )
    first, last = datetime(2025, 1, 1, tzinfo=UTC), datetime(2030, 1, 1, tzinfo=UTC)
    return ics_calendar.build(read_.items, name=cal.name, timezone="UTC", first=first, last=last)


async def _apply(state, data, calendar_id):
    with tenant_scope("default"):
        async with state.session_factory() as db:
            cal = (
                await db.execute(select(Calendar).where(Calendar.id == calendar_id))
            ).scalar_one()
            imp = await make_import(db, cal, data=data)
            await db.commit()
    assert await run(state, imp.id) == "done"
    await queue(state, imp.id, publish=True, grants=PUBLISHER)
    assert await run(state, imp.id) == "done"
    return imp.id


async def _typed(state, event_id):
    with tenant_scope("default"):
        async with state.session_factory() as db:
            event = (await db.execute(select(Event).where(Event.id == event_id))).scalar_one()
            return event.type, json.dumps(event.extra)


async def test_uninstalled_type_survives_export_import_and_reimport(events_app):
    """Export with the feed writer, change the event so the file differs, import (an update
    through the shared write core), import the same file again: type and ``extra`` never move."""
    _app, state = events_app
    with tenant_scope("default"):
        async with state.session_factory() as db:
            cal = (await seed(db))["P"]
            event = await seed_event(db, cal, title="Talk", status="published", venue_name="Old")
            event.type, event.extra = GONE, RAW
            await db.flush()
            data = await _export(db, cal)
            event.venue_name = "Changed here"
            await db.commit()
            event_id, calendar_id = event.id, cal.id
    wanted = json.dumps(RAW)
    first = await _apply(state, data, calendar_id)
    imp, items, _events = await read(state, first)
    assert [i.verdict for i in items] == ["update"] and imp.updated == 1
    kind, extra = await _typed(state, event_id)
    assert (kind, extra) == (GONE, wanted)
    with tenant_scope("default"):
        async with state.session_factory() as db:
            row = (await db.execute(select(Event).where(Event.id == event_id))).scalar_one()
            assert row.venue_name == "Old"  # the update really ran
    second = await _apply(state, data, calendar_id)
    imp2, _items2, _ = await read(state, second)
    assert imp2.updated == 0 and imp2.created == 0
    assert await _typed(state, event_id) == (GONE, wanted)


async def test_import_on_a_calendar_with_plugin_sources_and_typed_events(events_app, monkeypatch):
    """Nothing imported gets a type or ``extra``; a typed event updated by file keeps both;
    a plugin item's UID in the file is a new event, and the importer never calls a source."""
    source = FakeSource("acme:fake", ok(item("k1", "From the plugin")), public=True)
    install(monkeypatch, source)
    _app, state = events_app
    with tenant_scope("default"):
        async with state.session_factory() as db:
            cal = (await seed(db))["P"]
            cal.sources = [{"id": "acme:fake", "settings": {}}]
            typed = await seed_event(db, cal, title="Typed", status="published", venue_name="V")
            typed.type, typed.extra = GONE, RAW
            await db.flush()
            await db.commit()
            typed_id, typed_uid, calendar_id = typed.id, typed.uid, cal.id
    plugin_uid = f"acme:fake:{calendar_id}:k1"
    data = corpus.calendar(
        *corpus.vevent(typed_uid, start="20260801T100000Z", end="20260801T110000Z"),
        *corpus.vevent(plugin_uid),
        *corpus.vevent("fresh@x", start="20260802T100000Z", end="20260802T110000Z"),
    )
    imp_id = await _apply(state, data, calendar_id)
    _imp, items, events = await read(state, imp_id)
    by_uid = {i.uid: i.verdict for i in items}
    assert by_uid[typed_uid] == "update"
    assert by_uid[plugin_uid] == "new" and by_uid["fresh@x"] == "new"  # never matched to a source
    assert source.calls == []
    for event in events:
        if event.id == typed_id:
            assert event.type == GONE and json.dumps(event.extra) == json.dumps(RAW)
        else:
            assert event.type == "event" and event.extra == {}
