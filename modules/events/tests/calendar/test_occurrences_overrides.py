"""Overrides in the occurrences read: skipped, cancelled and moved."""

from __future__ import annotations

from sm_events.calendar.occurrence import OccurrenceFilters
from sm_events.models import OccurrenceOverride

from tests.support.access import seed_calendars
from tests.support.calendars import seed_series
from tests.support.occurrences import OWNER, read, utc

V, E, P, M = "events.view", "events.edit", "events.publish", "events.manage"
VIENNA = "Europe/Vienna"
ALL = OccurrenceFilters()


async def _override(db, event, original_start, kind, **fields):
    db.add(
        OccurrenceOverride(event_id=event.id, original_start=original_start, kind=kind, **fields)
    )
    await db.flush()


async def test_overrides_applied(db):
    cals = await seed_calendars(db)
    ev = await seed_series(
        db, cals["I"], "FREQ=DAILY", "2026-07-01T10:00", "2026-07-01T11:00", status="published"
    )
    await _override(db, ev, utc(2026, 7, 2, 8), "skipped")
    await _override(db, ev, utc(2026, 7, 3, 8), "cancelled")
    await _override(
        db,
        ev,
        utc(2026, 7, 4, 8),
        "moved",
        starts_at=utc(2026, 7, 4, 14),
        ends_at=utc(2026, 7, 4, 15),
    )
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 6))
    by_day = {(o.start.day, o.start.hour): o for o in page.items}
    assert (2, 8) not in by_day  # skipped
    assert by_day[3, 8].status == "cancelled"
    assert (4, 8) not in by_day
    moved = by_day[4, 14]
    assert moved.key == f"{ev.id}:20260704T080000Z"  # keeps its original key
    assert moved.original_start == utc(2026, 7, 4, 8)
    assert by_day[1, 8].status == "confirmed" and by_day[5, 8].status == "confirmed"


async def test_moved_into_window_from_outside(db):
    cals = await seed_calendars(db)
    ev = await seed_series(
        db, cals["I"], "FREQ=WEEKLY", "2026-06-03T10:00", "2026-06-03T11:00", status="published"
    )
    # last month's instance moved into July
    await _override(
        db,
        ev,
        utc(2026, 6, 10, 8),
        "moved",
        starts_at=utc(2026, 7, 2, 9),
        ends_at=utc(2026, 7, 2, 10),
    )
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 4))
    assert [o.start for o in page.items] == [utc(2026, 7, 1, 8), utc(2026, 7, 2, 9)]
    assert page.items[1].original_start == utc(2026, 6, 10, 8)


async def test_moved_into_window_from_an_ended_series(db):
    """The series ended before the window; its moved instance is still shown."""
    cals = await seed_calendars(db)
    ev = await seed_series(
        db,
        cals["I"],
        "FREQ=WEEKLY;COUNT=3",
        "2026-05-06T10:00",
        "2026-05-06T11:00",
        status="published",
    )
    await _override(
        db,
        ev,
        utc(2026, 5, 13, 8),
        "moved",
        starts_at=utc(2026, 7, 2, 9),
        ends_at=utc(2026, 7, 2, 10),
    )
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 4))
    assert [o.start for o in page.items] == [utc(2026, 7, 2, 9)]


async def test_moved_out_of_window_disappears(db):
    cals = await seed_calendars(db)
    ev = await seed_series(
        db, cals["I"], "FREQ=DAILY", "2026-07-01T10:00", "2026-07-01T11:00", status="published"
    )
    await _override(
        db,
        ev,
        utc(2026, 7, 2, 8),
        "moved",
        starts_at=utc(2026, 8, 2, 9),
        ends_at=utc(2026, 8, 2, 10),
    )
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 4))
    assert [o.start.day for o in page.items] == [1, 3]


async def test_cancelled_event_marks_all(db):
    cals = await seed_calendars(db)
    await seed_series(
        db,
        cals["I"],
        "FREQ=DAILY;COUNT=3",
        "2026-07-01T10:00",
        "2026-07-01T11:00",
        status="published",
        cancelled=True,
    )
    page = await read(db, OWNER, utc(2026, 7, 1), utc(2026, 7, 10))
    assert len(page.items) == 3 and {o.status for o in page.items} == {"cancelled"}


async def test_skip_on_a_31_day_instance_reaches_the_last_hour_across_a_fall_back(db):
    """31 wall-clock days from 2026-09-30 10:00 to 2026-10-31 10:00 Vienna span the
    clocks going back: 31 days and an hour (08:00Z to 09:00Z). A read starting in the
    last half hour must still find the skip written for it."""
    cals = await seed_calendars(db)
    ev = await seed_series(
        db, cals["I"], "FREQ=YEARLY", "2026-09-30T10:00", "2026-10-31T10:00", status="published"
    )
    window = utc(2026, 10, 31, 8, 30), utc(2026, 10, 31, 9, 0)
    assert len((await read(db, OWNER, *window)).items) == 1
    await _override(db, ev, utc(2026, 9, 30, 8), "skipped")
    assert (await read(db, OWNER, *window)).items == []
