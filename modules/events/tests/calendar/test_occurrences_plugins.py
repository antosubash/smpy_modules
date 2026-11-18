"""Plugin sources in the occurrences read: merged, capped, reported, isolated."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_events.calendar import registry
from sm_events.calendar.extension_types import SourceViewer
from sm_events.calendar.occurrence import OccurrenceFilters
from sm_events.calendar.occurrences import occurrences
from sm_events.core import constants

from tests.support.access import seed_calendars
from tests.support.calendars import seed_event
from tests.support.occurrences import OWNER, utc
from tests.support.sources import FakeSource, floods, install, item, ok, raises, returns

SV = SourceViewer(user_id="o", roles=(), permissions=frozenset({"events.view"}))
START, END = utc(2026, 7, 1), utc(2026, 8, 1)


@pytest.fixture
def fake(monkeypatch):
    source = FakeSource("acme:fake")
    install(monkeypatch, source)
    yield source
    registry.reset_registry()


async def setup(db, behave, *, enabled=True):
    cal = (await seed_calendars(db))["I"]
    if enabled:
        cal.sources = [{"id": "acme:fake", "settings": {}}]
    await db.flush()
    return cal


async def read(db, filters=OccurrenceFilters(), source_viewer=SV, who=OWNER):
    return await occurrences(
        db,
        tenant_id="default",
        viewer=who,
        start=START,
        end=END,
        filters=filters,
        default_locale="en",
        source_viewer=source_viewer,
    )


def at(day, hour, key, title="P"):
    return item(
        key,
        title,
        start=datetime(2026, 7, day, hour, tzinfo=UTC),
        end=datetime(2026, 7, day, hour + 1, tzinfo=UTC),
    )


async def test_merged_in_order(db, fake):
    cal = await setup(db, None)
    await seed_event(db, cal, title="early", status="published", starts_at=utc(2026, 7, 6, 6))
    await seed_event(db, cal, title="late", status="published", starts_at=utc(2026, 7, 8, 12))
    fake._behave = ok(at(7, 9, "mid", "mid"), at(9, 9, "last", "last"))
    page = await read(db)
    assert [(o.title, o.source) for o in page.items] == [
        ("early", "events"),
        ("mid", "acme:fake"),
        ("late", "events"),
        ("last", "acme:fake"),
    ]
    keys = [(o.start, o.end, o.source, o.key) for o in page.items]
    assert keys == sorted(keys)
    plugin = page.items[1]
    assert (plugin.editable, plugin.type, plugin.event_id, plugin.calendar_id) == (
        False,
        "event",
        None,
        cal.id,
    )


async def test_cap_counts_plugin_items(db, fake, monkeypatch):
    cal = await setup(db, None)
    monkeypatch.setattr(constants, "MAX_OCCURRENCES", 30)
    first = utc(2026, 7, 1, 0)
    for i in range(25):
        await seed_event(
            db, cal, title=f"e{i}", status="published", starts_at=first + timedelta(hours=i)
        )
    fake._behave = ok(*[at(20 + i // 10, i % 10, f"p{i}") for i in range(10)])
    page = await read(db)
    assert len(page.items) == 30 and page.truncated
    assert sum(1 for o in page.items if o.source == "acme:fake") == 5  # cut by time, not by source


async def test_statuses_reported(db, fake):
    cal = await setup(db, None)
    fake._behave = ok(at(7, 9, "a"))
    page = await read(db)
    assert [(s.id, s.calendar_id, s.status, s.code) for s in page.sources] == [
        ("acme:fake", cal.id, "ok", None)
    ]


async def test_builtin_never_in_statuses(db, fake):
    await setup(db, None, enabled=False)
    page = await read(db)
    assert page.sources == []


async def test_types_filter_excludes_plugins_unless_it_names_the_default_type(db, fake):
    """A plugin's item is of the default type: a filter narrower than that drops it."""
    cal = await setup(db, None)
    await seed_event(db, cal, title="own", status="published", type="event")
    fake._behave = ok(at(7, 9, "a"))
    other = await read(db, OccurrenceFilters(types=frozenset({"nothing"})))
    assert other.items == [] and other.sources == [] and fake.calls == []
    default = await read(db, OccurrenceFilters(types=frozenset({"event"})))
    assert sorted(o.source for o in default.items) == ["acme:fake", "events"]


async def test_sources_events_only_excludes_plugins(db, fake):
    cal = await setup(db, None)
    await seed_event(db, cal, title="own", status="published", starts_at=utc(2026, 7, 3, 9))
    fake._behave = ok(at(7, 9, "a"))
    page = await read(db, OccurrenceFilters(sources=frozenset({"events"})))
    assert [o.source for o in page.items] == ["events"] and page.sources == []
    assert fake.calls == []
    only_plugin = await read(db, OccurrenceFilters(sources=frozenset({"acme:fake"})))
    assert [o.source for o in only_plugin.items] == ["acme:fake"]


@pytest.mark.parametrize("behave", [raises, returns("garbage"), returns([object()])])
async def test_failing_source_keeps_builtin(db, fake, behave):
    cal = await setup(db, None)
    await seed_event(db, cal, title="own", status="published", starts_at=utc(2026, 7, 3, 9))
    fake._behave = behave
    page = await read(db)
    assert [o.title for o in page.items] == ["own"]
    assert page.sources[0].status == "failed"


async def test_a_plugin_truncation_marks_the_page(db, fake):
    await setup(db, None)
    fake._behave = floods(600)
    page = await read(db)
    assert page.truncated and page.sources[0].status == "truncated"
    assert len(page.items) == 500


async def test_without_a_source_viewer_a_signed_in_read_skips_plugins(db, fake):
    await setup(db, None)
    fake._behave = ok(at(7, 9, "a"))
    page = await read(db, source_viewer=None)
    assert page.items == [] and fake.calls == []
    assert [(s.status, s.code) for s in page.sources] == [("skipped", "no_viewer")]


async def test_viewer_reaches_the_source(db, fake):
    await setup(db, None)
    await read(db)
    ((ctx, start, end),) = fake.calls
    assert ctx.viewer == SV and (start, end) == (START, END)
    assert ctx.locale == "en"


async def test_category_filter_excludes_plugins_console_read(db, fake):
    import uuid

    await setup(db, None)
    fake._behave = ok(at(7, 9, "a"))
    page = await read(db, OccurrenceFilters(category_ids=frozenset({uuid.uuid4()})))
    assert page.items == [] and page.sources == [] and fake.calls == []


async def test_keys_are_unique_across_calendars(db, fake):
    cals = await seed_calendars(db)
    for letter in ("I", "U"):
        cals[letter].sources = [{"id": "acme:fake", "settings": {}}]
    await db.flush()
    fake._behave = ok(at(7, 9, "same"))
    page = await read(db)
    keys = [o.key for o in page.items if o.source == "acme:fake"]
    assert len(keys) == 2 and len(set(keys)) == 2
    assert {o.calendar_id for o in page.items} == {cals["I"].id, cals["U"].id}
