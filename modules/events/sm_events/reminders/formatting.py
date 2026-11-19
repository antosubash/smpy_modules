"""Dates and times for the mail: in the EVENT's zone, in the follower's language.

The zone is named (``CEST``) because the reader may be anywhere; nothing is said about the
reader's own zone (the framework keeps none, and a guessed one would be wrong). All-day events
are dates only, a multi-day one a range of dates; a timed event on one day is
``date, start - end zone``, across days ``date start - date end``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from babel.dates import format_date, format_time

from sm_events.reminders import strings

__all__ = ["format_when", "short_date"]

DASH = chr(0x2013)  # an en dash, spelled so no tool rewrites it


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:  # an unknown name: UTC, loudly named, rather than a wrong local time
        return ZoneInfo("UTC")


def short_date(value: datetime, *, timezone: str, locale: str) -> str:
    zone = _zone(timezone)
    return format_date(value.astimezone(zone).date(), format="medium", locale=locale)


def _time(value: datetime, zone: ZoneInfo, locale: str) -> str:
    return format_time(value.astimezone(UTC), format="short", tzinfo=zone, locale=locale)


def format_when(
    *, start: datetime, end: datetime, all_day: bool, timezone: str, locale: str
) -> str:
    zone, loc = _zone(timezone), strings.catalogue_locale(locale)
    first, last = start.astimezone(zone), end.astimezone(zone)
    if all_day:
        day1 = first.date()
        day2 = (last - timedelta(microseconds=1)).date()
        text = format_date(day1, format="full", locale=loc)
        if day2 > day1:
            text += f" {DASH} {format_date(day2, format='full', locale=loc)}"
        return strings.text("when_all_day", loc, date=text)
    date1 = format_date(first.date(), format="full", locale=loc)
    time1, time2 = _time(first, zone, loc), _time(last, zone, loc)
    zone1, zone2 = first.tzname() or "", last.tzname() or ""
    left = f"{date1}, {time1}" + (f" {zone1}" if zone1 != zone2 else "")
    if first.date() == last.date():
        return f"{left} {DASH} {time2} {zone2}"
    date2 = format_date(last.date(), format="full", locale=loc)
    return f"{left} {DASH} {date2}, {time2} {zone2}"
