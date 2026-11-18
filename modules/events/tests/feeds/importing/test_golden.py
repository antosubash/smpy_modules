"""Export with PR 4's writer, import into another calendar: the same events come back."""

from __future__ import annotations

from datetime import UTC, datetime

from sm_events.core.tenancy import tenant_scope
from sm_events.feeds import ics_calendar
from sm_events.feeds.select import feed_events
from sm_events.models import (
    Calendar,
    Event,
    EventText,
    OccurrenceOverride,
    Visibility,
)
from sqlalchemy import select

from tests.feeds.importing.runner_support import PUBLISHER, queue, run
from tests.feeds.importing.staging_support import make_import
from tests.support.calendars import seed_event, seed_series

NOW = datetime(2026, 6, 1, tzinfo=UTC)


async def _source(db) -> Calendar:
    cal = Calendar(slug="src", name="Source", owner_id="o", visibility=Visibility.PUBLIC)
    db.add(cal)
    await db.flush()
    series = await seed_series(
        db, cal, "FREQ=WEEKLY;COUNT=6", "2026-07-06T10:00", "2026-07-06T11:30",
        status="published", venue_name="Hall 1", latitude=48.2, longitude=16.37,
    )  # fmt: skip
    for text in (
        await db.execute(select(EventText).where(EventText.event_id == series.id))
    ).scalars():
        text.title, text.description = "Weekly concert", "<p>Bring a friend</p>"
    vienna_noon = lambda day, hour: datetime(2026, 7, day, hour, tzinfo=UTC)  # noqa: E731
    db.add_all(
        [
            OccurrenceOverride(
                event_id=series.id, original_start=vienna_noon(13, 8), kind="skipped"
            ),
            OccurrenceOverride(
                event_id=series.id, original_start=vienna_noon(20, 8), kind="cancelled"
            ),
            OccurrenceOverride(
                event_id=series.id,
                original_start=vienna_noon(27, 8),
                kind="moved",
                starts_at=vienna_noon(27, 13),
                ends_at=vienna_noon(27, 14),
            ),
        ]
    )
    await seed_event(
        db, cal, title="Conference", status="published", all_day=True,
        starts_at=datetime(2026, 7, 9, 22, tzinfo=UTC),
        ends_at=datetime(2026, 7, 12, 22, tzinfo=UTC),
        timezone="Europe/Vienna", cancelled=False,
    )  # fmt: skip
    await seed_event(
        db, cal, title="Called off", status="published", cancelled=True,
        starts_at=datetime(2026, 8, 3, 8, tzinfo=UTC), ends_at=datetime(2026, 8, 3, 9, tzinfo=UTC),
    )  # fmt: skip
    await seed_event(
        db, cal, title="UTC thing", status="published",
        starts_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
        ends_at=datetime(2026, 9, 1, 13, tzinfo=UTC),
    )  # fmt: skip
    await db.flush()
    return cal


async def _export(db, cal) -> bytes:
    read = await feed_events(
        db,
        calendar_id=cal.id,
        locale="en",
        default_locale="en",
        now=NOW,
        url_for=lambda slug, loc: f"https://example.org/{slug}",
        events=select(Event).where(Event.tenant_id == "default"),
    )
    assert len(read.items) == 4 and not read.truncated
    first, last = datetime(2025, 1, 1, tzinfo=UTC), datetime(2030, 1, 1, tzinfo=UTC)
    return ics_calendar.build(read.items, name=cal.name, timezone="UTC", first=first, last=last)


async def _shape(db, calendar_id):
    events = list(
        (
            await db.execute(
                select(Event).where(Event.calendar_id == calendar_id).order_by(Event.starts_at)
            )
        ).scalars()
    )
    out = {}
    for event in events:
        text = (
            (await db.execute(select(EventText).where(EventText.event_id == event.id)))
            .scalars()
            .first()
        )
        overrides = sorted(
            (
                (o.original_start, o.kind, o.starts_at, o.ends_at)
                for o in (
                    await db.execute(
                        select(OccurrenceOverride).where(OccurrenceOverride.event_id == event.id)
                    )
                ).scalars()
            ),
            key=lambda o: o[0],
        )
        out[event.uid] = {
            "all_day": event.all_day,
            "timezone": event.timezone,
            "starts_at": event.starts_at,
            "ends_at": event.ends_at,
            "rrule": event.rrule,
            "cancelled": event.cancelled,
            "venue": event.venue_name,
            "coords": (event.latitude, event.longitude),
            "title": text.title,
            "description": text.description,
            "overrides": overrides,
        }
    return out


async def test_golden_round_trip(events_app):
    _app, state = events_app
    with tenant_scope("default"):
        async with state.session_factory() as db:
            source = await _source(db)
            data = await _export(db, source)
            target = Calendar(
                slug="dst", name="Destination", owner_id="o", default_timezone="Europe/Vienna"
            )
            db.add(target)
            await db.flush()
            imp = await make_import(db, target, data=data)
            original = await _shape(db, source.id)
            await db.commit()
    assert await run(state, imp.id) == "done"
    await queue(state, imp.id, publish=True, grants=PUBLISHER)
    assert await run(state, imp.id) == "done"
    with tenant_scope("default"):
        async with state.session_factory() as db:
            copied = await _shape(db, target.id)
    assert set(copied) == set(original)  # the same UIDs, kept verbatim
    for uid, want in original.items():
        got = copied[uid]
        zone = want["timezone"] if want["timezone"] != "UTC" else "Europe/Vienna"
        assert got["timezone"] == zone, uid  # a UTC time is shown in the calendar's own zone
        for field in (
            "all_day",
            "starts_at",
            "ends_at",
            "rrule",
            "cancelled",
            "venue",
            "coords",
            "title",
            "overrides",
        ):
            assert got[field] == want[field], (uid, field)
        assert "Bring a friend" in got["description"] or "Bring a friend" not in want["description"]
    imp_row = (await _read(state, imp.id))[0]
    assert (imp_row.created, imp_row.skipped, imp_row.failed) == (4, 0, 0)


async def _read(state, import_id):
    from tests.feeds.importing.runner_support import read

    return await read(state, import_id)


async def test_golden_reimport_is_noop(events_app):
    _app, state = events_app
    with tenant_scope("default"):
        async with state.session_factory() as db:
            source = await _source(db)
            data = await _export(db, source)
            target = Calendar(
                slug="dst", name="Destination", owner_id="o", default_timezone="Europe/Vienna"
            )
            db.add(target)
            await db.flush()
            first = await make_import(db, target, data=data)
            await db.commit()
    await run(state, first.id)
    await queue(state, first.id, publish=True, grants=PUBLISHER)
    await run(state, first.id)
    with tenant_scope("default"):
        async with state.session_factory() as db:
            again = await make_import(db, target, data=data)
            await db.commit()
    await run(state, again.id)
    await queue(state, again.id, publish=True, grants=PUBLISHER)
    assert await run(state, again.id) == "done"
    imp, items, _events = await _read(state, again.id)
    assert (imp.unchanged, imp.created, imp.updated, imp.skipped, imp.failed) == (4, 0, 0, 0, 0)
    assert {i.outcome for i in items} == {"unchanged"}
