"""``OccurrenceFilters.event_ids``: the occurrences of named events only (what a card reads)."""

from __future__ import annotations

import pytest
from sm_events.calendar import registry
from sm_events.calendar.occurrence import OccurrenceFilters
from sm_events.core.access.public import ANONYMOUS
from sm_events.models import OccurrenceOverride

from tests.support.access import seed_calendars
from tests.support.calendars import seed_event, seed_series
from tests.support.occurrences import OWNER, read, utc
from tests.support.sources import FakeSource, install, item, ok

START, END = utc(2026, 7, 1), utc(2026, 7, 22)


async def _cast(db):
    cal = (await seed_calendars(db))["U"]
    one = await seed_event(db, cal, title="one", status="published", starts_at=utc(2026, 7, 3, 9))
    series = await seed_series(
        db,
        cal,
        "FREQ=WEEKLY;BYDAY=WE",
        "2026-07-01T10:00",
        "2026-07-01T11:00",
        title="weekly",
        status="published",
    )
    other = await seed_event(db, cal, title="other", status="published", starts_at=utc(2026, 7, 4))
    return cal, one, series, other


async def test_event_ids_filter(db):
    _cal, one, series, other = await _cast(db)
    page = await read(db, OWNER, START, END, OccurrenceFilters(event_ids=frozenset({series.id})))
    assert {o.event_id for o in page.items} == {series.id}
    assert [o.title for o in page.items] == ["weekly"] * 3
    both = await read(
        db, OWNER, START, END, OccurrenceFilters(event_ids=frozenset({one.id, other.id}))
    )
    assert [o.title for o in both.items] == ["one", "other"]
    nothing = await read(db, OWNER, START, END, OccurrenceFilters(event_ids=frozenset()))
    assert nothing.items == []
    everything = await read(db, OWNER, START, END, OccurrenceFilters())
    assert len(everything.items) == 5


async def test_event_ids_keeps_overrides(db):
    _cal, _one, series, _other = await _cast(db)
    # 2026-07-01 10:00 Vienna is 08:00Z; the next two are 7/8 and 7/15.
    db.add(
        OccurrenceOverride(event_id=series.id, original_start=utc(2026, 7, 8, 8), kind="skipped")
    )
    db.add(
        OccurrenceOverride(
            event_id=series.id,
            original_start=utc(2026, 7, 15, 8),
            kind="moved",
            starts_at=utc(2026, 7, 16, 12),
            ends_at=utc(2026, 7, 16, 13),
        )
    )
    await db.flush()
    page = await read(db, OWNER, START, END, OccurrenceFilters(event_ids=frozenset({series.id})))
    assert [o.start for o in page.items] == [utc(2026, 7, 1, 8), utc(2026, 7, 16, 12)]
    assert page.items[1].original_start == utc(2026, 7, 15, 8)


@pytest.fixture
def fake(monkeypatch):
    source = FakeSource("acme:fake", public=True)
    install(monkeypatch, source)
    yield source
    registry.reset_registry()


async def test_event_ids_skips_plugin_sources(db, fake):
    cal, _one, series, _other = await _cast(db)
    cal.sources = [{"id": "acme:fake", "settings": {}}]
    await db.flush()
    fake._behave = ok(item("a", "Plugin item"))
    public = OccurrenceFilters(include_unpublished=False)
    plain = await read(db, ANONYMOUS, START, END, public)
    assert "acme:fake" in {o.source for o in plain.items}
    fake.calls.clear()
    narrowed = OccurrenceFilters(include_unpublished=False, event_ids=frozenset({series.id}))
    page = await read(db, ANONYMOUS, START, END, narrowed)
    assert {o.source for o in page.items} == {"events"}
    assert page.sources == [] and fake.calls == []
