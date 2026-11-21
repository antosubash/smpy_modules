"""Expansion on the master's wall clock: DST, all-day, windows and bounds."""

from __future__ import annotations

import itertools
import time
from datetime import UTC, datetime, timedelta

from sm_events.calendar import rrule
from sm_events.calendar.expand import instances, is_occurrence
from sm_events.calendar.times import to_span

VIENNA = "Europe/Vienna"


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def run(
    text,
    start,
    end,
    window,
    *,
    tz=VIENNA,
    all_day=False,
    until="derive",
):
    sp = to_span(all_day=all_day, timezone=tz, start=start, end=end, recurring=True)
    rule = rrule.parse(text, all_day=all_day, timezone=tz)
    if until == "derive":
        until = rrule.validate(rule, sp, all_day=all_day, timezone=tz)
    return list(
        instances(
            rule=rule,
            span=sp,
            all_day=all_day,
            timezone=tz,
            window_start=window[0],
            window_end=window[1],
            recurrence_until=until,
        )
    )


def test_weekly_keeps_wall_clock_across_dst():
    got = run(
        "FREQ=WEEKLY;COUNT=4",
        "2026-03-16T10:00",
        "2026-03-16T11:00",
        (utc(2026, 3, 1), utc(2026, 5, 1)),
    )
    assert [i.start.hour for i in got] == [9, 9, 8, 8]
    assert [i.start.day for i in got] == [16, 23, 30, 6]
    assert all(i.end - i.start == timedelta(hours=1) for i in got)


def test_autumn_change_back():
    got = run(
        "FREQ=WEEKLY;COUNT=3",
        "2026-10-19T10:00",
        "2026-10-19T11:00",
        (utc(2026, 10, 1), utc(2026, 12, 1)),
    )
    assert [i.start.hour for i in got] == [8, 9, 9]  # 26 October is the first CET Monday


def test_gap_instance_shifts_forward():
    got = run(
        "FREQ=DAILY;COUNT=3",
        "2026-03-28T02:30",
        "2026-03-28T03:00",
        (utc(2026, 3, 27), utc(2026, 4, 5)),
    )
    assert [i.start for i in got] == [
        utc(2026, 3, 28, 1, 30),
        utc(2026, 3, 29, 1, 30),
        utc(2026, 3, 30, 0, 30),
    ]
    assert got[1].end - got[1].start == timedelta(minutes=30)  # the exact duration


def test_fold_instance_takes_first():
    got = run(
        "FREQ=DAILY;COUNT=3",
        "2026-10-24T02:30",
        "2026-10-24T03:00",
        (utc(2026, 10, 23), utc(2026, 11, 5)),
    )
    assert [i.start for i in got] == [
        utc(2026, 10, 24, 0, 30),
        utc(2026, 10, 25, 0, 30),
        utc(2026, 10, 26, 1, 30),
    ]


def test_all_day_series_days_not_hours():
    got = run(
        "FREQ=WEEKLY;COUNT=3",
        "2026-03-22",
        "2026-03-22",
        (utc(2026, 3, 1), utc(2026, 5, 1)),
        all_day=True,
    )
    assert [i.end - i.start for i in got] == [
        timedelta(hours=24),
        timedelta(hours=23),  # 29 March
        timedelta(hours=24),
    ]
    assert got[1].start == utc(2026, 3, 28, 23)


def test_window_overlap_from_before():
    # three-day instances every week; the window opens in the middle of one
    args = ("FREQ=WEEKLY;COUNT=4", "2026-07-06T10:00", "2026-07-08T10:00")
    got = run(*args, (utc(2026, 7, 14, 8), utc(2026, 7, 14, 12)))
    assert [i.start for i in got] == [utc(2026, 7, 13, 8)]
    assert run(*args, (utc(2026, 7, 15, 8), utc(2026, 7, 15, 12))) == []  # ended at 15 July 08:00Z
    assert run(*args, (utc(2026, 7, 15, 7, 59), utc(2026, 7, 15, 12)))[0].start == utc(
        2026, 7, 13, 8
    )


def test_window_end_is_exclusive():
    args = ("FREQ=DAILY", "2026-07-01T10:00", "2026-07-01T11:00")
    got = run(*args, (utc(2026, 7, 1), utc(2026, 7, 3, 8)))
    assert [i.start.day for i in got] == [1, 2]
    assert [i.start.day for i in run(*args, (utc(2026, 7, 1), utc(2026, 7, 3, 8, 1)))] == [1, 2, 3]


def test_lazy_and_bounded():
    sp = to_span(
        all_day=False,
        timezone=VIENNA,
        start="2026-01-01T10:00",
        end="2026-01-01T11:00",
        recurring=True,
    )
    rule = rrule.parse("FREQ=DAILY", all_day=False, timezone=VIENNA)

    def gen():
        return instances(
            rule=rule,
            span=sp,
            all_day=False,
            timezone=VIENNA,
            window_start=utc(2026, 6, 1),
            window_end=utc(2027, 6, 1),
            recurrence_until=None,
        )

    began = time.monotonic()
    assert len(list(itertools.islice(gen(), 5))) == 5
    assert time.monotonic() - began < 0.05
    assert len(list(gen())) in (365, 366)


def test_is_occurrence():
    sp = to_span(
        all_day=False,
        timezone=VIENNA,
        start="2026-07-01T10:00",
        end="2026-07-01T11:00",
        recurring=True,
    )
    rule = rrule.parse("FREQ=DAILY;COUNT=3", all_day=False, timezone=VIENNA)
    kw = {"rule": rule, "span": sp, "all_day": False, "timezone": VIENNA}
    third = utc(2026, 7, 3, 8)
    assert is_occurrence(third, **kw)
    assert not is_occurrence(third + timedelta(minutes=1), **kw)
    assert not is_occurrence(utc(2026, 7, 4, 8), **kw)  # the fourth does not exist
    assert not is_occurrence(utc(2026, 6, 30, 8), **kw)


def test_is_occurrence_gap_instance_uses_stored_start():
    sp = to_span(
        all_day=False,
        timezone=VIENNA,
        start="2026-03-28T02:30",
        end="2026-03-28T03:00",
        recurring=True,
    )
    rule = rrule.parse("FREQ=DAILY", all_day=False, timezone=VIENNA)
    kw = {"rule": rule, "span": sp, "all_day": False, "timezone": VIENNA}
    assert is_occurrence(utc(2026, 3, 29, 1, 30), **kw)  # 03:30 local, shifted out of the gap
    assert not is_occurrence(utc(2026, 3, 29, 0, 30), **kw)


def test_month_end_rule_in_expansion():
    got = run(
        "FREQ=MONTHLY;BYMONTHDAY=31",
        "2026-01-31T10:00",
        "2026-01-31T11:00",
        (utc(2026, 1, 1), utc(2027, 1, 1)),
        tz="UTC",
    )
    assert [i.start.month for i in got] == [1, 3, 5, 7, 8, 10, 12]
