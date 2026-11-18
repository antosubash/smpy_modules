"""Dates, times and zones, read from a file's own text (Ruling 22).

No library parses these and no zone definition in the file is ever used: a ``TZID`` is looked up
in the IANA database (``zoneinfo``) or in a fixed Windows-name table (``icalendar``'s CLDR
copy, used as data only) and is otherwise **unknown**, which skips the item: a file's
``VTIMEZONE`` could define any offsets, and evaluating it is the zone bomb this module refuses.
Nothing here ever silently shifts an instant: a UTC time stays the same instant and is shown in
the event's zone; a floating one is read in the calendar's zone and noted; a local time that does
not exist (a DST gap) is moved forward as RFC 5545 section 3.3.5 says and noted; one that occurs
twice is its first occurrence, as everywhere in the module.

Output is PR 2's local wall-clock strings, so :func:`sm_events.calendar.times.to_span` has the
last word on length and order.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sm_events.calendar.times import localize
from sm_events.core import constants
from sm_events.feeds.importing.scan import Prop

__all__ = ["ItemSkip", "When", "read_instants", "read_when", "resolve_tzid"]

_DATE: Final = re.compile(r"(\d{4})(\d{2})(\d{2})", re.ASCII)
_DATETIME: Final = re.compile(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)", re.ASCII)
_DURATION: Final = re.compile(
    r"([+-])?P(?:(\d{1,6})W)?(?:(\d{1,6})D)?(?:T(?:(\d{1,6})H)?(?:(\d{1,6})M)?(?:(\d{1,6})S)?)?",
    re.ASCII,
)
_ZONE_NAME: Final = re.compile(r"[A-Za-z0-9_+\-/]{1,64}", re.ASCII)
_TZONE_PREFIX: Final = "tzone://Microsoft/"
_ONE_DAY: Final = timedelta(days=1)
_MAX_DURATION: Final = timedelta(days=constants.MAX_EVENT_DAYS + 1)


class ItemSkip(Exception):  # noqa: N818 - a verdict, not an error
    """The item cannot be imported; ``code`` is the reason shown in the preview."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class When:
    all_day: bool
    timezone: str
    start: str
    end: str
    notes: tuple[str, ...]


def _windows_table() -> dict[str, str]:
    from icalendar.timezone.windows_to_olson import WINDOWS_TO_OLSON

    return WINDOWS_TO_OLSON


def resolve_tzid(tzid: str | None) -> str | None:
    """The IANA zone a ``TZID`` names, else ``None`` (unknown: never evaluated, never guessed).

    An IANA name must be in the database; a Windows name (also as Outlook's
    ``tzone://Microsoft/<name>``) maps through ``icalendar``'s CLDR table."""
    if not tzid:
        return None
    name = tzid.removeprefix(_TZONE_PREFIX)
    if len(name) > 64 or not name.isprintable():
        return None
    if _ZONE_NAME.fullmatch(name):
        try:
            return ZoneInfo(name).key
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    mapped = _windows_table().get(name)
    if mapped is not None:
        try:
            return ZoneInfo(mapped).key
        except (ZoneInfoNotFoundError, ValueError, OSError):
            return None
    return None


def _skip(code: str = "invalid_times") -> ItemSkip:
    return ItemSkip(code)


@dataclass(frozen=True)
class _Value:
    day: date
    clock: time | None  # None: a date
    utc: bool
    tz: str | None  # a resolved TZID, else None


def _year_ok(year: int) -> bool:
    return constants.ORIGINAL_START_MIN_YEAR <= year < constants.ORIGINAL_START_MAX_YEAR


def _read(text: str, params: dict[str, str] | None = None) -> _Value:
    text = text.strip()
    params = params or {}
    tzid = params.get("TZID")
    zone = None
    if tzid is not None:
        zone = resolve_tzid(tzid)
        if zone is None:
            raise ItemSkip("unknown_timezone")
    try:
        if (found := _DATETIME.fullmatch(text)) is not None:
            y, mo, d, h, mi, s, z = found.groups()
            if not _year_ok(int(y)):
                raise ValueError
            when = datetime(int(y), int(mo), int(d), int(h), int(mi), min(int(s), 59))
            if int(s) > 60 or int(h) > 23:
                raise ValueError
            return _Value(when.date(), when.time(), bool(z), zone)
        if (found := _DATE.fullmatch(text)) is not None:
            y, mo, d = (int(g) for g in found.groups())
            if not _year_ok(y):
                raise ValueError
            return _Value(date(y, mo, d), None, False, None)
    except ValueError:
        raise _skip() from None
    raise _skip()


def _duration(text: str) -> timedelta:
    found = _DURATION.fullmatch(text.strip())
    if found is None or text.strip() in ("P", "+P", "-P") or text.strip().endswith("T"):
        raise _skip()
    sign, weeks, days, hours, minutes, seconds = found.groups()
    if not any((weeks, days, hours, minutes, seconds)):
        raise _skip()
    total = timedelta(
        weeks=int(weeks or 0),
        days=int(days or 0),
        hours=int(hours or 0),
        minutes=int(minutes or 0),
        seconds=int(seconds or 0),
    )
    if sign == "-" or total <= timedelta(0) or total > _MAX_DURATION:
        raise _skip()
    return total


def _local(instant: datetime, zone: str) -> str:
    local = instant.astimezone(ZoneInfo(zone))
    text = local.strftime("%Y-%m-%dT%H:%M")
    return f"{text}:{local.second:02d}" if local.second else text


def _instant(value: _Value, zone: str, notes: list[str]) -> datetime:
    """The aware UTC instant of a timed value read in ``zone`` (its own TZID wins)."""
    assert value.clock is not None
    if value.utc:
        return datetime.combine(value.day, value.clock, tzinfo=UTC)
    tz = ZoneInfo(value.tz or zone)
    naive = datetime.combine(value.day, value.clock)
    instant = localize(naive, tz)
    if instant.astimezone(tz).replace(tzinfo=None) != naive and "shifted_local_time" not in notes:
        notes.append("shifted_local_time")
    return instant


def _prop(props: Sequence[Prop], name: str) -> Prop | None:
    return next((p for p in props if p.name == name), None)


def _all_day_value(prop: Prop) -> bool:
    return prop.params.get("VALUE", "").upper() == "DATE" or bool(
        _DATE.fullmatch(prop.value.strip())
    )


def read_when(props: Sequence[Prop], *, calendar_tz: str, into: str | None = None) -> When:
    """The event's local times and zone, or :class:`ItemSkip` (``unknown_timezone`` or
    ``invalid_times``). ``into`` expresses a timed event in that zone instead of its own (an
    override moved within its series, which lives in the series' zone)."""
    start_prop = _prop(props, "DTSTART")
    if start_prop is None:
        raise _skip()
    start = _read(start_prop.value, start_prop.params)
    end_prop, duration_prop = _prop(props, "DTEND"), _prop(props, "DURATION")
    end = _read(end_prop.value, end_prop.params) if end_prop is not None else None
    if end is not None and (end.clock is None) != (start.clock is None):
        raise _skip()
    notes: list[str] = []
    if start.clock is None:
        return _read_all_day(start, end, duration_prop, calendar_tz, into)
    zone = into or start.tz or calendar_tz
    if start.tz is None and not start.utc:
        notes.append("floating_time")
    begins = _instant(start, calendar_tz, notes)
    if end is not None:
        finishes = _instant(end, calendar_tz, notes)
    elif duration_prop is not None:
        finishes = begins + _duration(duration_prop.value)
    else:
        finishes = begins + constants.IMPORT_DEFAULT_DURATION
        notes.append("default_duration")
    return When(False, zone, _local(begins, zone), _local(finishes, zone), tuple(notes))


def _read_all_day(
    start: _Value, end: _Value | None, duration: Prop | None, calendar_tz: str, into: str | None
) -> When:
    zone = into or calendar_tz
    if end is not None:
        last = end.day - _ONE_DAY  # DTEND is exclusive; the module's end is the last day
    elif duration is not None:
        text = duration.value.strip()
        if "T" in text.upper():  # whole days only
            raise _skip()
        last = start.day + _duration(text) - _ONE_DAY
    else:
        last = start.day  # a date is one day (RFC 5545)
    return When(True, zone, start.day.isoformat(), last.isoformat(), ())


def read_instants(prop: Prop, *, tz: str, all_day: bool) -> list[datetime]:
    """The UTC instants an ``EXDATE`` or ``RECURRENCE-ID`` names, one per comma-separated value.
    A date (all-day series) is its local midnight in ``tz``; a timed value is its own ``TZID``,
    ``Z``, or ``tz``. A value of the other kind or a bad one is :class:`ItemSkip`."""
    values = prop.value.split(",")
    if len(values) > constants.IMPORT_MAX_EXDATES + 1:
        raise ItemSkip("too_many_overrides")
    found: list[datetime] = []
    notes: list[str] = []
    for raw in values:
        value = _read(raw, prop.params)
        if (value.clock is None) != all_day:
            raise _skip()
        if value.clock is None:
            found.append(localize(datetime.combine(value.day, time.min), ZoneInfo(tz)))
        else:
            found.append(_instant(value, tz, notes))
    return found
