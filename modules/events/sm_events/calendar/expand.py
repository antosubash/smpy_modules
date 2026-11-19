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
from sm_events.calendar.times import Span, all_day_dates, day_exists, localize
from sm_events.core import constants

__all__ = ["Instance", "instances", "is_occurrence"]

_MARGIN = timedelta(days=constants.LOOK_BACK_MARGIN_DAYS)  # exact filtering is done in UTC
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
    ascending by start.

    A local date that does not exist (a zone skipping a whole day) has no instance:
    it is dropped, never mapped onto the next day's instant, though ``COUNT`` has
    counted it (see :func:`sm_events.calendar.rrule.validate`)."""
    tz = ZoneInfo(timezone)
    if all_day:
        first, after = all_day_dates(span, timezone)
        length = after - first
        reach = length
        last_date = (
            None if recurrence_until is None else _naive(recurrence_until, tz).date() - length
        )
        last_start = None
    else:
        reach = duration = span.ends_at - span.starts_at
        last_date = None
        last_start = None if recurrence_until is None else recurrence_until - duration
    upper = _naive(window_end, tz) + _MARGIN
    for loose in (
        rr.until_local(rule, tz),
        None if last_start is None else _naive(last_start, tz) + _MARGIN,
    ):
        if loose is not None:
            upper = min(upper, loose)
    if last_date is not None:
        upper = min(upper, datetime.combine(last_date, time(23, 59, 59)))
    walk = rr.iterate(
        rule,
        dtstart_local=rr.local_start(span, tz, all_day=all_day),
        lower_local=_naive(window_start, tz) - reach - _MARGIN,
        until_local=upper,
    )
    for hit in walk:
        if not rr.within_until(rule, hit, tz) or (last_date is not None and hit.date() > last_date):
            return
        start = localize(hit, tz)
        if last_start is not None and start > last_start:
            return
        if start.astimezone(tz).date() != hit.date() and not day_exists(hit.date(), tz):
            continue
        if start >= window_end:
            return
        end = (
            localize(datetime.combine(hit.date() + length, time.min), tz)
            if all_day
            else start + duration
        )
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
