"""The list's range rule: a series intersects, a one-off overlaps."""

from __future__ import annotations

from datetime import UTC, datetime

from sm_events.content.listing import EventFilters, list_events

from tests.support.access import seed_calendars
from tests.support.calendars import seed_event, seed_series
from tests.support.writes import OWNER_P


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


async def found(db, **kw) -> set:
    rows, _total = await list_events(db, OWNER_P, EventFilters(**kw), page=1, page_size=50)
    return {r.id for r in rows}


async def test_one_off_intersects_range(db):
    cal = (await seed_calendars(db))["I"]
    event = await seed_event(db, cal, starts_at=utc(2026, 7, 1, 10), ends_at=utc(2026, 7, 1, 12))
    assert await found(db, start=utc(2026, 7, 1, 11), end=utc(2026, 7, 1, 13)) == {event.id}
    assert await found(db, start=utc(2026, 7, 1, 12)) == set()  # ends exactly at the range start
    assert await found(db, end=utc(2026, 7, 1, 10)) == set()  # starts exactly at the range end
    assert await found(db, start=utc(2026, 7, 1, 9), end=utc(2026, 7, 1, 10, 1)) == {event.id}
    assert await found(db, start=utc(2026, 7, 1, 11, 59)) == {event.id}
    assert await found(db) == {event.id}


async def test_series_intersects_range(db):
    cal = (await seed_calendars(db))["I"]
    endless = await seed_series(
        db, cal, "FREQ=WEEKLY;BYDAY=WE", "2026-07-01T10:00", "2026-07-01T11:00"
    )
    finite = await seed_series(
        db, cal, "FREQ=DAILY;COUNT=3", "2026-07-01T10:00", "2026-07-01T11:00"
    )
    # a series matches from its first start on, however far the range is
    assert await found(db, start=utc(2030, 1, 1), end=utc(2030, 2, 1)) == {endless.id}
    assert await found(db, start=utc(2026, 7, 2), end=utc(2026, 7, 3)) == {endless.id, finite.id}
    assert await found(db, start=utc(2026, 7, 3, 9, 1)) == {
        endless.id
    }  # after the last instance ended
    assert await found(db, start=utc(2026, 7, 3, 8, 59)) == {endless.id, finite.id}
    assert await found(db, end=utc(2026, 7, 1, 8)) == set()  # before either begins
    assert await found(db, end=utc(2026, 7, 1, 8, 1)) == {endless.id, finite.id}


async def test_paging_and_total(db):
    cal = (await seed_calendars(db))["I"]
    for hour in range(1, 6):
        await seed_event(db, cal, starts_at=utc(2026, 7, 1, hour))
    rows, total = await list_events(db, OWNER_P, EventFilters(), page=2, page_size=2)
    assert total == 5 and [r.starts_at.hour for r in rows] == [3, 4]
    rows, total = await list_events(db, OWNER_P, EventFilters(), page=3, page_size=2)
    assert [r.starts_at.hour for r in rows] == [5]
