"""Expanding a series on the event's own wall clock. Pure and lazy.

The rule runs on the master's *local* naive clock, so "weekly at 10:00 Vienna"
stays at 10:00 across both DST changes (UTC 09:00 -> 08:00). An instance that
lands in a spring gap shifts forward by the gap, one in an autumn fold takes the
first occurrence. A timed instance lasts the master's exact duration, an all-day
one the master's number of days.

Nothing here iterates without a bound: the walk stops at the window's end or the
series' ``recurrence_until``, whichever is first (see :mod:`sm_events.calendar.rrule`).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sm_events.calendar import rrule as rr
from sm_events.calendar.times import Span, all_day_dates, localize

__all__ = ["Instance", "instances", "is_occurrence"]

_MARGIN = timedelta(days=1)  # absorbs a UTC offset change; exact filtering is done in UTC
_TICK = timedelta(microseconds=1)


@dataclass(frozen=True)
class Instance:
    original_start: datetime  # UTC
    start: datetime  # UTC
    end: datetime  # UTC


def _naive(value: datetime, tz: ZoneInfo) -> datetime:
    return value.astimezone(tz).replace(tzinfo=None)


def instances(
    *,
    rule: rr.Rule,
    span: Span,
    all_day: bool,
    timezone: str,
    window_start: datetime,
    window_end: datetime,
    recurrence_until: datetime | None,
) -> Iterator[Instance]:
    """Instances whose ``[start, end)`` meets ``[window_start, window_end)``,
    ascending by start."""
    tz = ZoneInfo(timezone)
    if all_day:
        first, after = all_day_dates(span, timezone)
        length = after - first

        def end_of(start_local: datetime, _start: datetime) -> datetime:
            return localize(datetime.combine(start_local.date() + length, time.min), tz)

        reach = length
        last_start = None if recurrence_until is None else _naive(recurrence_until, tz) - length
    else:
        duration = span.ends_at - span.starts_at

        def end_of(_start_local: datetime, start: datetime) -> datetime:
            return start + duration

        reach = duration
        last_start = None if recurrence_until is None else _naive(recurrence_until - duration, tz)
    upper = _naive(window_end, tz) + _MARGIN
    if last_start is not None:
        upper = min(upper, last_start)  # exact: the last instance, not one more
    own = rr.until_local(rule, tz)
    if own is not None:
        upper = min(upper, own)
    lower = _naive(window_start, tz) - reach - _MARGIN
    walk = rr.iterate(
        rule,
        dtstart_local=_naive(span.starts_at, tz),
        lower_local=lower,
        until_local=upper,
    )
    for hit in walk:
        start = localize(hit.replace(hour=0, minute=0, second=0) if all_day else hit, tz)
        if start >= window_end:
            return
        end = end_of(hit, start)
        if end > window_start:
            yield Instance(original_start=start, start=start, end=end)


def is_occurrence(
    original_start: datetime,
    *,
    rule: rr.Rule,
    span: Span,
    all_day: bool,
    timezone: str,
    recurrence_until: datetime | None = None,
) -> bool:
    """Is ``original_start`` (UTC) exactly the start of one of the rule's instances?

    A ``COUNT`` rule is bounded by its stored ``recurrence_until``; without one it
    is derived (``validate`` iterates at most the 100-year horizon)."""
    if rule.count is not None and recurrence_until is None:
        recurrence_until = rr.validate(rule, span, all_day=all_day, timezone=timezone)
    found = instances(
        rule=rule,
        span=span,
        all_day=all_day,
        timezone=timezone,
        window_start=original_start,
        window_end=original_start + _TICK,
        recurrence_until=recurrence_until,
    )
    return any(item.original_start == original_start for item in found)
