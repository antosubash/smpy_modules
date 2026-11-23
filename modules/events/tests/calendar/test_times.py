"""Local wall clock <-> UTC: storage, gaps, folds and bounds."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sm_events.calendar.times import (
    Span,
    all_day_dates,
    is_nonexistent,
    to_local,
    to_span,
)
from sm_events.core.errors import InvalidTimes

VIENNA = "Europe/Vienna"


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def span(start, end, *, all_day=False, tz=VIENNA, recurring=False):
    return to_span(all_day=all_day, timezone=tz, start=start, end=end, recurring=recurring)


def test_timed_round_trip():
    got = span("2026-07-01T10:00", "2026-07-01T11:30")
    assert got == Span(utc(2026, 7, 1, 8), utc(2026, 7, 1, 9, 30))
    assert to_local(got, all_day=False, timezone=VIENNA) == (
        "2026-07-01T10:00",
        "2026-07-01T11:30",
    )


def test_seconds_kept_when_not_zero():
    got = span("2026-07-01T10:00:05", "2026-07-01T11:30")
    assert to_local(got, all_day=False, timezone=VIENNA)[0] == "2026-07-01T10:00:05"


def test_all_day_storage_on_short_day():
    got = span("2026-03-29", "2026-03-29", all_day=True)
    assert got.starts_at == utc(2026, 3, 28, 23)
    assert got.ends_at == utc(2026, 3, 29, 22)
    assert got.ends_at - got.starts_at == timedelta(hours=23)
    first, after = all_day_dates(got, VIENNA)
    assert (first.isoformat(), after.isoformat()) == ("2026-03-29", "2026-03-30")
    assert to_local(got, all_day=True, timezone=VIENNA) == ("2026-03-29", "2026-03-29")


def test_all_day_multi_day_inclusive_end():
    got = span("2026-08-01", "2026-08-03", all_day=True)
    assert got.starts_at == utc(2026, 7, 31, 22)
    assert got.ends_at == utc(2026, 8, 3, 22)  # local midnight of 4 August
    assert to_local(got, all_day=True, timezone=VIENNA) == ("2026-08-01", "2026-08-03")


def test_gap_is_refused():
    with pytest.raises(InvalidTimes) as caught:
        span("2026-03-29T02:30", "2026-03-29T04:00")
    assert caught.value.code == "invalid_local_time"
    with pytest.raises(InvalidTimes) as caught:
        span("2026-03-29T01:00", "2026-03-29T02:30")
    assert caught.value.code == "invalid_local_time"


def test_fold_takes_first():
    got = span("2026-10-25T02:30", "2026-10-25T04:00")
    assert got.starts_at == utc(2026, 10, 25, 0, 30)


def test_end_before_start():
    with pytest.raises(InvalidTimes) as caught:
        span("2026-07-01T10:00", "2026-07-01T10:00")
    assert caught.value.code == "end_before_start"
    assert span("2026-07-01", "2026-07-01", all_day=True)
    with pytest.raises(InvalidTimes) as caught:
        span("2026-07-02", "2026-07-01", all_day=True)
    assert caught.value.code == "end_before_start"


def test_duration_bounds():
    assert span("2026-01-01T00:00", "2027-01-02T00:00", tz="UTC")  # 366 days
    with pytest.raises(InvalidTimes) as caught:
        span("2026-01-01T00:00", "2027-01-02T00:01", tz="UTC")
    assert caught.value.code == "duration_too_long"
    assert span("2026-01-01", "2026-12-31", all_day=True)  # 365 days
    assert span("2026-01-01", "2027-01-01", all_day=True)  # 366 days
    with pytest.raises(InvalidTimes) as caught:
        span("2026-01-01", "2027-01-02", all_day=True)
    assert caught.value.code == "duration_too_long"


def test_series_duration_bounds():
    assert span("2026-01-01T00:00", "2026-02-01T00:00", tz="UTC", recurring=True)  # 31 days
    with pytest.raises(InvalidTimes) as caught:
        span("2026-01-01T00:00", "2026-02-01T00:01", tz="UTC", recurring=True)
    assert caught.value.code == "duration_too_long"
    assert span("2026-01-01", "2026-01-31", all_day=True, recurring=True)
    with pytest.raises(InvalidTimes) as caught:
        span("2026-01-01", "2026-02-01", all_day=True, recurring=True)
    assert caught.value.code == "duration_too_long"


def test_dst_hour_cannot_tip_a_31_day_series():
    # 31 wall-clock days across the autumn change is 31 days + 1 h of UTC.
    assert span("2026-10-01T10:00", "2026-11-01T10:00", recurring=True)


@pytest.mark.parametrize(
    "bad",
    [
        "2026-07-01T10:00+02:00",
        "2026-07-01T10:00Z",
        "2026-07-01 10:00",
        "2026-07-01",
        "2026-13-01T10:00",
        "2026-07-01T25:00",
        "",
    ],
)
def test_malformed_timed_input_refused(bad):
    with pytest.raises(InvalidTimes) as caught:
        span(bad, "2026-07-02T10:00")
    assert caught.value.code == "invalid_local_time"


@pytest.mark.parametrize("bad", ["2026-07-01T10:00", "2026-02-30", "26-07-01"])
def test_malformed_all_day_input_refused(bad):
    with pytest.raises(InvalidTimes) as caught:
        span(bad, "2026-07-02", all_day=True)
    assert caught.value.code == "invalid_local_time"


def test_is_nonexistent():
    tz = ZoneInfo(VIENNA)
    assert is_nonexistent(datetime(2026, 3, 29, 2, 30), tz)
    assert not is_nonexistent(datetime(2026, 3, 29, 3, 0), tz)
    assert not is_nonexistent(datetime(2026, 10, 25, 2, 30), tz)  # a fold exists, not a gap


def test_southern_hemisphere_and_half_hour_zones():
    # Sydney springs forward on the first Sunday of October.
    assert is_nonexistent(datetime(2026, 10, 4, 2, 30), ZoneInfo("Australia/Sydney"))
    # Lord Howe moves by 30 minutes: 02:00 -> 02:30.
    lord_howe = ZoneInfo("Australia/Lord_Howe")
    assert is_nonexistent(datetime(2026, 10, 4, 2, 15), lord_howe)
    assert not is_nonexistent(datetime(2026, 10, 4, 2, 30), lord_howe)
    got = span("2026-04-05T01:45", "2026-04-05T03:00", tz="Australia/Lord_Howe")
    assert got.ends_at > got.starts_at


ZONES = [
    "Europe/Vienna",
    "America/New_York",
    "Australia/Sydney",
    "Australia/Lord_Howe",
    "Pacific/Apia",
    "UTC",
]


def test_property_round_trip():
    rng = random.Random(0)
    checked = 0
    for _ in range(500):
        name = rng.choice(ZONES)
        tz = ZoneInfo(name)
        start = datetime(2000, 1, 1) + timedelta(minutes=rng.randrange(0, 31 * 365 * 24 * 60))
        end = start + timedelta(minutes=rng.randrange(1, 3 * 24 * 60))
        if is_nonexistent(start, tz) or is_nonexistent(end, tz):
            with pytest.raises(InvalidTimes):
                span(
                    start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes"), tz=name
                )
            continue
        text = (start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes"))
        got = span(*text, tz=name)
        assert to_local(got, all_day=False, timezone=name) == text
        checked += 1
    assert checked > 400


def test_property_all_day_round_trip():
    rng = random.Random(1)
    for _ in range(300):
        name = rng.choice(ZONES)
        first = datetime(2000, 1, 1) + timedelta(days=rng.randrange(0, 31 * 365))
        last = first + timedelta(days=rng.randrange(0, 20))
        text = (first.date().isoformat(), last.date().isoformat())
        got = span(*text, all_day=True, tz=name)
        assert to_local(got, all_day=True, timezone=name) == text
        days = all_day_dates(got, name)
        assert (days[1] - days[0]).days == (last - first).days + 1
