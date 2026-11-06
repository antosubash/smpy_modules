"""The report timeline: first opens and first clicks in UTC calendar buckets (T14 / B6).

Pure: it reads no database. A campaign's first 72 hours are hourly, a longer one
daily for at most 90 days. The window is ``[b0, b0 + n * bucket)`` with an
exclusive end; an event outside it is dropped here (the report's totals still
count it). A naive datetime is UTC, as ``AwareDateTime`` hands back on SQLite.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

__all__ = ["HOURLY_WINDOW", "MAX_DAYS", "Bucket", "Point", "bucketize"]

HOURLY_WINDOW = timedelta(hours=72)
MAX_DAYS = 90
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)

Bucket = Literal["hour", "day"]


@dataclass(frozen=True)
class Point:
    at: datetime
    opens: int
    clicks: int


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _ceil_div(span: timedelta, unit: timedelta) -> int:
    return -((-span) // unit)


def bucketize(
    opens: Sequence[datetime],
    clicks: Sequence[datetime],
    *,
    start: datetime,
    now: datetime,
) -> tuple[Bucket, list[Point]]:
    """The window's points and the bucket size they use."""
    start, now = _utc(start), _utc(now)
    b0 = start.replace(minute=0, second=0, microsecond=0)
    bucket: Bucket = "hour"
    step, cap = HOUR, 72
    if now - b0 > HOURLY_WINDOW:
        bucket, step, cap = "day", DAY, MAX_DAYS
        b0 = b0.replace(hour=0)
    n = min(cap, max(1, _ceil_div(now - b0, step)))
    opened = [0] * n
    clicked = [0] * n
    for counts, events in ((opened, opens), (clicked, clicks)):
        for event in events:
            index = (_utc(event) - b0) // step
            if 0 <= index < n:
                counts[index] += 1
    return bucket, [Point(b0 + step * i, opened[i], clicked[i]) for i in range(n)]
