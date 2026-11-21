"""All-day, gap, fold and leap-day edges of expansion (review findings T2-T6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_events.calendar import rrule
from sm_events.calendar.expand import instances, is_occurrence
from sm_events.calendar.times import to_span


def _series(text, *, tz, start, end, all_day):
    sp = to_span(all_day=all_day, timezone=tz, start=start, end=end, recurring=True)
    rule = rrule.parse(text, all_day=all_day, timezone=tz)
    return rule, sp, rrule.validate(rule, sp, all_day=all_day, timezone=tz)


def _read(rule, sp, until, *, tz, all_day, start=None, end=None):
    return list(
        instances(
            rule=rule,
            span=sp,
            all_day=all_day,
            timezone=tz,
            window_start=start or sp.starts_at - timedelta(days=1),
            window_end=end or sp.starts_at + timedelta(days=400),
            recurrence_until=until,
        )
    )


@pytest.mark.parametrize(
    ("tz", "day", "count"),
    [("America/Sao_Paulo", "2018-11-04", 3), ("America/Havana", "2026-03-08", 10)],
)
def test_all_day_series_starting_in_a_midnight_gap_keeps_its_last_day(tz, day, count):
    rule, sp, until = _series(f"FREQ=WEEKLY;COUNT={count}", tz=tz, start=day, end=day, all_day=True)
    got = _read(rule, sp, until, tz=tz, all_day=True)
    first = datetime.fromisoformat(day).date()
    assert [i.start.astimezone(__import__("zoneinfo").ZoneInfo(tz)).date() for i in got] == [
        first + timedelta(weeks=n) for n in range(count)
    ]
    for item in got:
        assert is_occurrence(
            item.original_start,
            rule=rule,
            span=sp,
            all_day=True,
            timezone=tz,
            recurrence_until=until,
        )


def test_leap_day_start_in_a_century_year_does_not_raise():
    # 2000-02-29 + 100 years is 2100, which has no 29 February.
    for all_day, start, end in (
        (False, "2000-02-29T10:00", "2000-02-29T11:00"),
        (True, "2000-02-29", "2000-02-29"),
    ):
        rule, sp, until = _series("FREQ=YEARLY", tz="UTC", start=start, end=end, all_day=all_day)
        assert until is None
        got = _read(rule, sp, until, tz="UTC", all_day=all_day)
        assert got[0].start == sp.starts_at
        assert rrule.add_years(datetime(2000, 2, 29), 100) == datetime(2100, 2, 28)


def test_a_day_a_zone_skips_has_no_instance_and_no_duplicate():
    tz = "Pacific/Apia"  # 30 December 2011 never happened
    rule, sp, until = _series(
        "FREQ=DAILY;COUNT=7",
        tz=tz,
        start="2011-12-27T10:00",
        end="2011-12-27T11:00",
        all_day=False,
    )
    got = _read(rule, sp, until, tz=tz, all_day=False)
    starts = [i.start for i in got]
    assert len(starts) == len(set(starts)) == 6  # COUNT counts the skipped day
    assert all(i.end - i.start == timedelta(hours=1) for i in got)
    # the last counted day is the 2nd of January, and the bound still reaches it
    assert starts[-1].astimezone(__import__("zoneinfo").ZoneInfo(tz)).date().isoformat() == (
        "2012-01-02"
    )


def test_all_day_in_a_skipped_day_is_dropped_not_zero_length():
    tz = "Pacific/Apia"
    rule, sp, until = _series(
        "FREQ=DAILY;COUNT=7", tz=tz, start="2011-12-27", end="2011-12-27", all_day=True
    )
    got = _read(rule, sp, until, tz=tz, all_day=True)
    assert len({i.original_start for i in got}) == len(got) == 6
    assert all(i.end > i.start for i in got)


def test_timed_utc_until_is_an_instant():
    """Vienna's clocks go back at 03:00 on 2026-10-25: 02:30 happens at 00:30Z and 01:30Z."""
    tz = "Europe/Vienna"
    rule, sp, until = _series(
        "FREQ=WEEKLY;UNTIL=20261025T010000Z",
        tz=tz,
        start="2026-10-18T02:30",
        end="2026-10-18T03:00",
        all_day=False,
    )
    got = _read(rule, sp, until, tz=tz, all_day=False)
    assert [i.start for i in got] == [
        datetime(2026, 10, 18, 0, 30, tzinfo=UTC),
        datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
    ]
    assert until == datetime(2026, 10, 25, 1, 0, tzinfo=UTC)
