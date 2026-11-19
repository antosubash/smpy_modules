"""Expansion against an independent oracle, in zones with every kind of clock change.

The oracle is written here and shares nothing with ``sm_events.calendar``: dateutil
expands the rule on naive local datetimes (``COUNT`` counted on them, as the plan's
rulings have it), then each one is localised with zoneinfo by the rulings' own rules:

* a time in a gap shifts forward by the gap (zoneinfo's ``fold=0``);
* a time that occurs twice takes its first occurrence;
* a local date with no instant at all (Pacific/Apia 2011-12-30, Pacific/Kiritimati
  1994-12-31) has no instance, and ``COUNT`` has still counted it;
* a timed instance lasts the master's exact duration, an all-day one its days.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from dateutil import rrule as du
from sm_events.calendar import rrule
from sm_events.calendar.expand import instances, is_occurrence
from sm_events.calendar.times import to_span

# zone -> a date shortly before one of its clock changes, and one for a leap-day series
ZONES = {
    "Europe/Vienna": date(2026, 3, 20),
    "America/New_York": date(2026, 3, 1),
    "America/Sao_Paulo": date(2018, 10, 28),  # DST at midnight until 2019
    "America/Havana": date(2026, 3, 1),  # DST at midnight
    "Asia/Beirut": date(2026, 3, 20),  # DST at midnight
    "Australia/Lord_Howe": date(2026, 3, 25),  # a 30-minute change
    "Pacific/Apia": date(2011, 12, 20),  # skipped 30 December 2011
    "Asia/Kolkata": date(2026, 1, 1),
    "UTC": date(2026, 1, 1),
    "Pacific/Kiritimati": date(1994, 12, 20),  # skipped 31 December 1994
    "Pacific/Niue": date(2026, 1, 1),
}
RULES = ["FREQ=DAILY", "FREQ=DAILY;COUNT=40", "FREQ=WEEKLY;COUNT=14", "FREQ=WEEKLY;INTERVAL=2"]
HOURS = (0, 1, 2, 3, 12, 23)
WINDOW_DAYS = 130


def _day_exists(day: date, tz: ZoneInfo) -> bool:
    noon = datetime.combine(day, time(12))
    return noon.replace(tzinfo=tz).astimezone(UTC).astimezone(tz).replace(tzinfo=None) == noon


def _utc(naive: datetime, tz: ZoneInfo) -> datetime:
    return naive.replace(tzinfo=tz).astimezone(UTC)


def _oracle(text, tz, begin, *, all_day, length):
    """``[(start, end)]`` UTC, ascending, for ``begin`` (a naive local datetime)."""
    out = []
    for naive in du.rrulestr(text, dtstart=begin):
        if naive > begin + timedelta(days=WINDOW_DAYS + 10):
            break
        if not _day_exists(naive.date(), tz):
            continue
        start = _utc(naive, tz)
        if all_day:
            end = _utc(datetime.combine(naive.date() + length, time.min), tz)
        else:
            end = start + length
        out.append((start, end))
    return out


def _series(name, day, hour, text, *, all_day):
    if all_day:
        start = end = day.isoformat()
    else:
        start, end = f"{day}T{hour:02d}:30", f"{day}T{hour:02d}:55"
    sp = to_span(all_day=all_day, timezone=name, start=start, end=end, recurring=True)
    rule = rrule.parse(text, all_day=all_day, timezone=name)
    return sp, rule, rrule.validate(rule, sp, all_day=all_day, timezone=name)


def _cases():
    for name, day in ZONES.items():
        for text in RULES:
            for hour in HOURS:
                yield name, day, hour, text, False
            yield name, day, 0, text, True


def _try(name, day, hour, text, all_day):
    try:
        return _series(name, day, hour, text, all_day=all_day)
    except Exception as exc:  # a start inside a gap is refused when typed
        assert getattr(exc, "code", None) == "invalid_local_time", exc
        return None


def test_expansion_equals_the_oracle():
    checked = 0
    for name, day, hour, text, all_day in _cases():
        made = _try(name, day, hour, text, all_day)
        if made is None:
            continue
        sp, rule, until = made
        tz = ZoneInfo(name)
        local = sp.starts_at.astimezone(tz).replace(tzinfo=None)
        if all_day:
            first = local.date()
            length = (sp.ends_at.astimezone(tz).date()) - first
            begin = datetime.combine(first, time.min)
        else:
            length, begin = sp.ends_at - sp.starts_at, local
        want = _oracle(text, tz, begin, all_day=all_day, length=length)
        w_start, w_end = (
            sp.starts_at - timedelta(days=3),
            sp.starts_at + timedelta(days=WINDOW_DAYS),
        )
        got = [
            (i.start, i.end)
            for i in instances(
                rule=rule,
                span=sp,
                all_day=all_day,
                timezone=name,
                window_start=w_start,
                window_end=w_end,
                recurrence_until=until,
            )
        ]
        context = (name, day, hour, text, all_day)
        assert [s for s, _ in got] == sorted({s for s, _ in got}), context  # distinct, ascending
        assert got == [w for w in want if w[0] < w_end and w[1] > w_start], context
        for start, _ in got:
            assert is_occurrence(
                start, rule=rule, span=sp, all_day=all_day, timezone=name, recurrence_until=until
            ), context
            assert not is_occurrence(
                start + timedelta(minutes=1),
                rule=rule,
                span=sp,
                all_day=all_day,
                timezone=name,
                recurrence_until=until,
            ), context
        checked += 1
    assert checked > 200


@pytest.mark.parametrize("all_day", [False, True])
def test_a_leap_day_start_in_2000_expands_like_the_oracle(all_day):
    name = "Europe/Vienna"
    tz = ZoneInfo(name)
    sp, rule, until = _series(name, date(2000, 2, 29), 10, "FREQ=YEARLY", all_day=all_day)
    assert until is None
    begin = datetime(2000, 2, 29, 0 if all_day else 10, 30 if not all_day else 0)
    length = timedelta(days=1) if all_day else timedelta(minutes=25)
    oracle = []
    for naive in du.rrulestr("FREQ=YEARLY", dtstart=begin):
        if naive.year > 2110:
            break
        start = _utc(naive, tz)
        end = (
            _utc(datetime.combine(naive.date() + length, time.min), tz)
            if all_day
            else start + length
        )
        oracle.append((start, end))
    got = [
        (i.start, i.end)
        for i in instances(
            rule=rule,
            span=sp,
            all_day=all_day,
            timezone=name,
            window_start=datetime(2000, 1, 1, tzinfo=UTC),
            window_end=datetime(2110, 12, 31, tzinfo=UTC),
            recurrence_until=None,
        )
    ]
    assert got == oracle
    assert [s.astimezone(tz).year for s, _ in got][-3:] == [2096, 2104, 2108]  # no 2100
