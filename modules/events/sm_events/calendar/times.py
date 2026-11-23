"""Local wall-clock times <-> stored UTC spans. Pure: no database, no clock.

The API speaks a local wall clock plus an IANA ``timezone``; storage is UTC.
An all-day event is stored as local midnight of its first day up to local
midnight of the day *after* its last (exclusive), both in UTC; the API's
all-day ``end`` is the inclusive last date.

A local time that does not exist (a DST gap) is refused when a person typed it
(:func:`to_span`); one that occurs twice takes its first occurrence (``fold=0``).
:func:`localize` is the lenient form the expansion uses: a gap is shifted forward
by its length, as RFC 5545 section 3.3.5 has it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sm_events.core import constants
from sm_events.core.errors import InvalidTimes

__all__ = [
    "Span",
    "all_day_dates",
    "day_exists",
    "is_nonexistent",
    "localize",
    "parse_local",
    "supported_instant",
    "to_local",
    "to_span",
]

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$")
_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class Span:
    """What is stored: aware UTC instants (all-day: the end is exclusive)."""

    starts_at: datetime
    ends_at: datetime


def localize(naive: datetime, tz: ZoneInfo) -> datetime:
    """A naive local time as aware UTC: ``fold=0``, a gap shifted forward."""
    return naive.replace(tzinfo=tz, fold=0).astimezone(UTC)


def is_nonexistent(naive: datetime, tz: ZoneInfo) -> bool:
    """Is the naive local time inside a DST gap? (It does not survive a round trip.)"""
    return localize(naive, tz).astimezone(tz).replace(tzinfo=None) != naive


def day_exists(day: date, tz: ZoneInfo) -> bool:
    """Does the local date have any instant? A zone that skips a whole day (Pacific/Apia,
    30 December 2011) has none: its midnight is shifted onto a later date."""
    return localize(datetime.combine(day, time.min), tz).astimezone(tz).date() == day


def _bad(
    detail: str, code: str = constants.INVALID_LOCAL_TIME_CODE, field: str | None = None
) -> InvalidTimes:
    return InvalidTimes(detail, code=code, field=field)


def _parse_date(text: str, field: str) -> date:
    if not isinstance(text, str) or not _DATE.match(text):
        raise _bad(constants.INVALID_LOCAL_TIME_DETAIL, field=field)
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _bad(constants.INVALID_LOCAL_TIME_DETAIL, field=field) from None


def parse_local(text: str, tz: ZoneInfo, field: str) -> datetime:
    """Naive wall clock; an offset, a ``Z`` or a nonexistent time is refused, naming ``field``."""
    if not isinstance(text, str) or not _DATETIME.match(text):
        raise _bad(constants.INVALID_LOCAL_TIME_DETAIL, field=field)
    try:
        naive = datetime.fromisoformat(text)
    except ValueError:
        raise _bad(constants.INVALID_LOCAL_TIME_DETAIL, field=field) from None
    if is_nonexistent(naive, tz):
        raise _bad(constants.INVALID_LOCAL_TIME_DETAIL, field=field)
    return naive


def supported_instant(value: datetime) -> datetime:
    """``value`` if its UTC instant lies in the years a calendar means; ``ValueError`` (a 422
    in a request) beyond. The offset is applied first: ``9999-12-31T23:59:59-05:00`` is
    year 10000 in UTC, which no column or zone arithmetic below can hold."""
    try:
        year = value.astimezone(UTC).year
    except OverflowError:
        year = 0
    if not constants.ORIGINAL_START_MIN_YEAR <= year < constants.ORIGINAL_START_MAX_YEAR:
        raise ValueError("outside the supported years")
    return value


def _midnight(day: date, tz: ZoneInfo) -> datetime:
    return localize(datetime.combine(day, time.min), tz)


def to_span(
    *,
    all_day: bool,
    timezone: str,
    start: str,
    end: str,
    recurring: bool,
    fields: tuple[str, str] = ("times.start", "times.end"),
) -> Span:
    """Parse and bound what a request sent. Raises :class:`InvalidTimes`, which
    names the input at fault: ``fields`` are the request's paths for start and end."""
    tz = ZoneInfo(timezone)
    limit = constants.MAX_SERIES_EVENT_DAYS if recurring else constants.MAX_EVENT_DAYS
    too_long = _bad(constants.DURATION_TOO_LONG_DETAIL, constants.DURATION_TOO_LONG_CODE, fields[1])
    before = _bad(constants.END_BEFORE_START_DETAIL, constants.END_BEFORE_START_CODE, fields[1])
    if all_day:
        first, last = _parse_date(start, fields[0]), _parse_date(end, fields[1])
        if last < first:
            raise before
        if (last - first).days + 1 > limit:
            raise too_long
        return Span(_midnight(first, tz), _midnight(last + _ONE_DAY, tz))
    begin, finish = parse_local(start, tz, fields[0]), parse_local(end, tz, fields[1])
    span = Span(localize(begin, tz), localize(finish, tz))
    if span.ends_at <= span.starts_at:
        raise before
    # Measured on the wall clock a person typed, so a DST hour cannot tip it over.
    if finish - begin > timedelta(days=limit):
        raise too_long
    return span


def _fmt(value: datetime) -> str:
    text = value.strftime("%Y-%m-%dT%H:%M")
    return f"{text}:{value.second:02d}" if value.second else text


def all_day_dates(span: Span, timezone: str) -> tuple[date, date]:
    """``(first day, exclusive end day)`` in the event's own timezone."""
    tz = ZoneInfo(timezone)
    return span.starts_at.astimezone(tz).date(), span.ends_at.astimezone(tz).date()


def to_local(span: Span, *, all_day: bool, timezone: str) -> tuple[str, str]:
    """The inverse of :func:`to_span`; an all-day end is the inclusive last date."""
    if all_day:
        first, after = all_day_dates(span, timezone)
        return first.isoformat(), (after - _ONE_DAY).isoformat()
    tz = ZoneInfo(timezone)
    return (
        _fmt(span.starts_at.astimezone(tz)),
        _fmt(span.ends_at.astimezone(tz)),
    )
