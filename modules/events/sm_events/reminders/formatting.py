"""Dates and times for the mail: in the EVENT's zone, in the follower's language.

The wording is the newsletter event card's, so the same event reads the same in both mails
(``scripts/tests/test_when_line_parity.py`` runs one case table through both): CLDR's narrow
no-break spaces become plain ones, an all-day event is dates only (a multi-day one a range), a
timed one on a single day is ``date, start-end zone`` and across days ``date, start zone - date,
end zone``. The zone is named by its tzdata abbreviation (``CEST``) because the reader may be
anywhere; nothing is said about the reader's own zone.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from babel.dates import format_date, format_time

from sm_events.core import timezones
from sm_events.reminders import strings

__all__ = ["format_when", "short_date", "zone_of"]

_EN: Final = chr(0x2013)  # an en dash, spelled so no tool rewrites it
_DASH: Final = f" {_EN} "
_SPACES: Final = str.maketrans({chr(0x202F): " ", chr(0xA0): " "})  # CLDR's narrow no-break spaces


def zone_of(name: str) -> ZoneInfo:
    """The event's zone; an unknown name is UTC (warned once), not a wrong local time."""
    return ZoneInfo(timezones.effective(name))


def _day(value: datetime, locale: str) -> str:
    return format_date(value.date(), format="full", locale=locale).translate(_SPACES)


def short_date(value: datetime, *, timezone: str, locale: str) -> str:
    local = value.astimezone(zone_of(timezone))
    return format_date(local.date(), format="medium", locale=locale)


def _time(value: datetime, locale: str) -> str:
    return format_time(value, format="short", locale=locale).translate(_SPACES)


def format_when(
    *, start: datetime, end: datetime, all_day: bool, timezone: str, locale: str
) -> str:
    zone, loc = zone_of(timezone), strings.catalogue_locale(locale)
    first, last = start.astimezone(zone), end.astimezone(zone)
    if all_day:
        day1 = first
        day2 = last - timedelta(microseconds=1)
        text = _day(day1, loc)
        if day2.date() > day1.date():
            text += f"{_DASH}{_day(day2, loc)}"
        return strings.text("when_all_day", loc, date=text)
    zone1, zone2 = first.tzname() or timezone, last.tzname() or timezone
    if first.date() == last.date():
        if zone1 == zone2:
            span = f"{_time(first, loc)}{_EN}{_time(last, loc)} {zone2}"
        else:
            span = f"{_time(first, loc)} {zone1}{_EN}{_time(last, loc)} {zone2}"
        return f"{_day(first, loc)}, {span}"
    return (
        f"{_day(first, loc)}, {_time(first, loc)} {zone1}{_DASH}"
        f"{_day(last, loc)}, {_time(last, loc)} {zone2}"
    )
