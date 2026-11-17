"""The read's own bounds: range, cap, truncation and runaway rules."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_events.calendar.occurrence import OccurrenceFilters
from sm_events.calendar.occurrences import occurrences
from sm_events.core.errors import InvalidRange
from sm_events.models import Event

from tests.support.access import principal, seed_calendars
from tests.support.calendars import seed_event, seed_series

OWNER = principal("o", "events.view", "events.edit", "events.publish")
ALL = OccurrenceFilters()


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


async def read(db, start, end, who=OWNER):
    return await occurrences(
        db,
        tenant_id="default",
        viewer=who,
        start=start,
        end=end,
        filters=ALL,
        default_locale="en",
    )


async def test_range_bounds(db):
    await seed_calendars(db)
    start = utc(2026, 1, 1)
    assert (await read(db, start, start + timedelta(days=366))).items == []
    with pytest.raises(InvalidRange) as caught:
        await read(db, start, start + timedelta(days=366, seconds=1))
    assert caught.value.code == "range_too_long" and caught.value.status_code == 422
    with pytest.raises(InvalidRange) as caught:
        await read(db, start, start)
    assert caught.value.code == "invalid_range"
    with pytest.raises(InvalidRange):
        await read(db, start, start - timedelta(days=1))
    with pytest.raises(ValueError):
        await read(db, datetime(2026, 1, 1), utc(2026, 2, 1))
    with pytest.raises(ValueError):
        await read(db, utc(2026, 1, 1), datetime(2026, 2, 1))


async def test_cap_and_truncation(db):
    cals = await seed_calendars(db)
    for n in range(10):
        await seed_series(
            db,
            cals["I"],
            "FREQ=DAILY",
            "2025-12-31T10:00",
            "2025-12-31T11:00",
            tz="UTC",
            title=f"s{n}",
            status="published",
        )
    page = await read(db, utc(2026, 1, 1), utc(2027, 1, 1))
    assert len(page.items) == 2000 and page.truncated
    keys = [(o.start, o.end, o.source, o.key) for o in page.items]
    assert keys == sorted(keys)
    # sorted from the start of the range: ten series, so 200 days' worth
    assert page.items[0].start == utc(2026, 1, 1, 10)
    assert page.items[-1].start == utc(2026, 7, 19, 10)


def _bulk(calendar, count, **fields):
    start = fields.pop("starts_at", utc(2026, 7, 1, 10))
    return [
        Event(
            id=uuid.uuid4(),
            uid=f"{uuid.uuid4()}@simple-module-events",
            calendar_id=calendar.id,
            starts_at=start + timedelta(minutes=n % 1000),
            ends_at=start + timedelta(minutes=n % 1000 + 30),
            timezone="UTC",
            status="published",
            **fields,
        )
        for n in range(count)
    ]


async def test_exact_cap_not_truncated(db):
    cals = await seed_calendars(db)
    db.add_all(_bulk(cals["I"], 2000))
    await db.flush()
    page = await read(db, utc(2026, 7, 1), utc(2026, 7, 3))
    assert len(page.items) == 2000 and not page.truncated
    db.add_all(_bulk(cals["I"], 1))
    await db.flush()
    page = await read(db, utc(2026, 7, 1), utc(2026, 7, 3))
    assert len(page.items) == 2000 and page.truncated


async def test_many_series_bounded(db):
    cals = await seed_calendars(db)
    db.add_all(
        _bulk(
            cals["I"],
            3000,
            starts_at=utc(2026, 6, 1, 10),
            rrule="FREQ=DAILY",
        )
    )
    await db.flush()
    began = time.monotonic()
    page = await read(db, utc(2026, 7, 1), utc(2026, 7, 31))
    assert time.monotonic() - began < 5
    assert len(page.items) == 2000 and page.truncated


@pytest.mark.parametrize(
    "text",
    [
        "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30",
        "FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30",
        "FREQ=WEEKLY;BYMONTH=4;BYMONTHDAY=31",
    ],
)
async def test_impossible_stored_rule_terminates(db, text):
    cals = await seed_calendars(db)
    await seed_event(
        db,
        cals["I"],
        status="published",
        starts_at=utc(2026, 2, 28, 10),
        rrule=text,
        recurrence_until=None,
    )
    began = time.monotonic()
    page = await read(db, utc(2026, 1, 1), utc(2026, 12, 31))
    assert time.monotonic() - began < 1
    assert page.items == []


async def test_a_corrupt_stored_rule_is_skipped(db):
    cals = await seed_calendars(db)
    await seed_event(db, cals["I"], status="published", rrule="FREQ=SECONDLY")
    ok = await seed_event(db, cals["I"], status="published", starts_at=utc(2026, 7, 2, 9))
    page = await read(db, utc(2026, 7, 1), utc(2026, 7, 5))
    assert [o.event_id for o in page.items] == [ok.id]
