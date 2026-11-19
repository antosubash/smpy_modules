"""``rrule.iterate`` equals plain dateutil for every allowed rule shape, in bounded work.

The oracle is ``dateutil.rrulestr`` on the rule text and a full walk from the series
start; the code under test jumps to the window and never walks past it.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from dateutil import rrule as du
from sm_events.calendar import rrule
from sm_events.calendar.expand import instances
from sm_events.calendar.times import to_span

SHAPES = {
    "DAILY": [
        "",
        "BYDAY=MO",
        "BYDAY=MO,WE;BYMONTH=2",
        "BYMONTH=2;BYMONTHDAY=29;BYDAY=MO",
        "BYMONTHDAY=-1",
        "BYMONTHDAY=1,15;BYSETPOS=1",
        "BYMONTHDAY=31",
    ],
    "WEEKLY": [
        "",
        "BYDAY=MO,WE,FR",
        "BYDAY=MO,SU;WKST=SU",
        "BYDAY=MO,TU;BYSETPOS=-1",
        "BYDAY=TU,TH;BYSETPOS=1,2",
        "BYMONTH=2;BYDAY=MO",
        "BYMONTHDAY=29;BYDAY=MO;BYMONTH=2",
        "WKST=SU",
        "BYMONTHDAY=-1;WKST=WE",
    ],
    "MONTHLY": [
        "",
        "BYDAY=2TU",
        "BYDAY=-1FR",
        "BYMONTHDAY=-1",
        "BYMONTHDAY=31",
        "BYDAY=MO,TU;BYSETPOS=-1",
        "BYMONTHDAY=29;BYMONTH=2",
        "BYDAY=5MO",
    ],
    "YEARLY": [
        "",
        "BYMONTH=2;BYMONTHDAY=29",
        "BYDAY=-1FR;BYMONTH=10",
        "BYMONTH=3;BYDAY=2SU",
        "BYMONTH=1,7;BYMONTHDAY=-1",
    ],
}
INTERVALS = (1, 2, 5)
STARTS = (datetime(2016, 2, 29, 10, 0), datetime(2020, 1, 15, 9, 30, 15))
OFFSETS = (
    timedelta(days=-400),
    timedelta(0),
    timedelta(days=365),
    timedelta(days=3650),
    timedelta(days=18250),
)
SPAN = timedelta(days=30)


def _cases():
    for freq, shapes in SHAPES.items():
        for shape in shapes:
            for interval in INTERVALS:
                text = f"FREQ={freq}" + (f";INTERVAL={interval}" if interval != 1 else "")
                yield text + (f";{shape}" if shape else "")


@pytest.mark.parametrize("start", STARTS, ids=lambda s: s.date().isoformat())
def test_iterate_equals_dateutil(start):
    checked = 0
    for text in _cases():
        rule = rrule.parse(text, all_day=False, timezone="UTC")
        for offset in OFFSETS:
            lower = (start + offset).replace(hour=0, minute=0, second=0)
            until = lower + SPAN
            oracle = du.rrulestr(text, dtstart=start)
            want = list(_between(oracle, lower, until))
            got = list(
                rrule.iterate(rule, dtstart_local=start, lower_local=lower, until_local=until)
            )
            assert got == want, (text, start, offset)
            checked += 1
    assert checked > 400


def _between(oracle, lower, until):
    for hit in oracle:
        if hit > until:
            return
        if hit >= lower:
            yield hit


def _series(text: str):
    sp = to_span(
        all_day=False,
        timezone="UTC",
        start="2016-02-29T10:00",
        end="2016-02-29T11:00",
        recurring=True,
    )
    return rrule.parse(text, all_day=False, timezone="UTC"), sp


def _expand(rule, sp):
    return list(
        instances(
            rule=rule,
            span=sp,
            all_day=False,
            timezone="UTC",
            window_start=datetime(2026, 11, 23, tzinfo=UTC),
            window_end=datetime(2026, 11, 30, tzinfo=UTC),
            recurrence_until=None,
        )
    )


def test_sparse_rule_stops_at_the_window():
    """Feb 29th on a Monday next recurs in 2044: reading November 2026 must not walk there."""
    rule, sp = _series("FREQ=DAILY;BYMONTH=2;BYMONTHDAY=29;BYDAY=MO")
    assert _expand(rule, sp) == []
    began = time.perf_counter()
    for _ in range(20):
        _expand(rule, sp)
    assert (time.perf_counter() - began) / 20 < 0.003  # was 11.6 ms


def test_two_hundred_sparse_series_are_a_cheap_read():
    rule, sp = _series("FREQ=DAILY;BYMONTH=2;BYMONTHDAY=29;BYDAY=MO")
    began = time.perf_counter()
    for _ in range(200):
        _expand(rule, sp)
    assert time.perf_counter() - began < 0.5  # was 2.3 s


@pytest.mark.parametrize(
    "text",
    [
        "FREQ=WEEKLY;INTERVAL=5;BYMONTH=2;BYMONTHDAY=29;BYDAY=MO",
        "FREQ=DAILY;INTERVAL=5;BYMONTH=2;BYMONTHDAY=29;BYDAY=MO",
    ],
)
def test_sparse_rule_with_an_interval_stops_at_the_window(text):
    rule, sp = _series(text)
    began = time.perf_counter()
    _expand(rule, sp)
    assert time.perf_counter() - began < 0.05
