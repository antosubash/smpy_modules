"""The report timeline's buckets (T14 / B6): UTC calendar buckets, an exclusive end."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sm_newsletter.tracking.timeline import bucketize

H = timedelta(hours=1)
D = timedelta(days=1)
START = datetime(2026, 11, 1, 10, 20, tzinfo=UTC)


def _counts(points, attr="opens"):
    return [getattr(p, attr) for p in points]


def test_start_off_the_hour():
    now = START + timedelta(hours=5)
    opens = [
        datetime(2026, 11, 1, 10, 5, tzinfo=UTC),
        datetime(2026, 11, 1, 10, 59, tzinfo=UTC),
        datetime(2026, 11, 1, 9, 59, tzinfo=UTC),
    ]
    bucket, points = bucketize(opens, [], start=START, now=now)
    assert bucket == "hour"
    assert [p.at.hour for p in points] == [10, 11, 12, 13, 14, 15]
    assert _counts(points) == [2, 0, 0, 0, 0, 0]


def test_exactly_72h_is_hourly():
    b0 = datetime(2026, 11, 1, 10, tzinfo=UTC)
    now = b0 + 72 * H
    last = b0 + timedelta(hours=71, minutes=59, seconds=59)
    bucket, points = bucketize([last, b0 + 72 * H], [b0], start=START, now=now)
    assert bucket == "hour" and len(points) == 72
    assert points[-1].opens == 1 and sum(_counts(points)) == 1
    assert points[0].clicks == 1


def test_just_over_72h_is_daily():
    now = datetime(2026, 11, 1, 10, tzinfo=UTC) + 72 * H + timedelta(seconds=1)
    bucket, points = bucketize([], [], start=START, now=now)
    assert bucket == "day"
    assert points[0].at == datetime(2026, 11, 1, tzinfo=UTC)
    assert len(points) == 4


def test_exactly_90_days():
    b0 = datetime(2026, 11, 1, tzinfo=UTC)
    now = b0 + 90 * D
    bucket, points = bucketize([b0 + 90 * D, b0 + 89 * D], [], start=START, now=now)
    assert bucket == "day" and len(points) == 90
    assert sum(_counts(points)) == 1 and points[-1].opens == 1


def test_window_caps_at_90_days():
    now = START + 200 * D
    late = datetime(2026, 11, 1, tzinfo=UTC) + 100 * D
    bucket, points = bucketize([late, START], [], start=START, now=now)
    assert bucket == "day" and len(points) == 90
    assert sum(_counts(points)) == 1


def test_start_late_in_utc_day():
    start = datetime(2026, 11, 1, 23, 30, tzinfo=UTC)
    bucket, points = bucketize([], [], start=start, now=start + 4 * D)
    assert bucket == "day"
    assert points[0].at == datetime(2026, 11, 1, tzinfo=UTC)
    assert len(points) == 5


def test_empty_inputs_give_zero_counts():
    _, points = bucketize([], [], start=START, now=START + 3 * H)
    assert len(points) == 4
    assert _counts(points) == [0] * 4 and _counts(points, "clicks") == [0] * 4


def test_now_before_start_is_one_point():
    _, points = bucketize([], [], start=START, now=START - H)
    assert len(points) == 1


def test_naive_datetimes_are_utc():
    naive_start = START.replace(tzinfo=None)
    naive_now = (START + 2 * H).replace(tzinfo=None)
    event = datetime(2026, 11, 1, 11, 30)
    aware = bucketize([event.replace(tzinfo=UTC)], [], start=START, now=START + 2 * H)
    naive = bucketize([event], [], start=naive_start, now=naive_now)
    assert naive == aware
    assert _counts(naive[1]) == [0, 1, 0]
    assert naive[1][0].at.tzinfo is not None
