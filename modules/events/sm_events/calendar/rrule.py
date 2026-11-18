"""RRULE: parse, validate, normalise and derive ``recurrence_until``. Pure.

Only an allow-list of parts is accepted (:mod:`sm_events.calendar.rrule_parts`) and
dateutil only ever sees keyword arguments built from it, never raw text. Iteration
lives in :mod:`sm_events.calendar.rrule_walk` (every walk has a stop; see there).

A series' dates are naive local ones. An all-day series' start is its first *date*
at 00:00, whatever instant a gap shifted its stored start to, so a rule and a
``COUNT`` are always counted in dates. ``UNTIL`` of a timed rule is an instant
(``Z``) and is compared as one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sm_events.calendar.rrule_parts import WEEKDAYS, ByDay, Parts, bad, parse_parts
from sm_events.calendar.rrule_walk import build, iterate
from sm_events.calendar.times import Span, all_day_dates, day_exists, localize
from sm_events.core import constants
from sm_events.core.errors import InvalidRule

__all__ = [
    "Rule",
    "add_years",
    "build",
    "iterate",
    "local_start",
    "parse",
    "until_local",
    "validate",
    "within_until",
]

_UNTIL_DATE_LEN = 8
_UNTIL_DATETIME_LEN = 16
_UNTIL_MARGIN = timedelta(days=1)  # absorbs a UTC offset change; compared exactly later
_MAX_YEAR = 9999


@dataclass(frozen=True)
class Rule:
    text: str  # normalised, no "RRULE:" prefix
    freq: str
    count: int | None
    until: datetime | date | None  # UTC aware (timed) or date (all-day)
    interval: int = 1
    bymonth: tuple[int, ...] = ()
    bymonthday: tuple[int, ...] = ()
    byday: ByDay = ()
    bysetpos: tuple[int, ...] = ()
    wkst: int | None = None


def _parse_until(text: str, *, all_day: bool, tz: ZoneInfo) -> datetime | date:
    """``YYYYMMDD`` or ``YYYYMMDDTHHMMSSZ``. A timed rule's date means the end of
    that local day; an all-day rule keeps only the date."""
    try:
        if len(text) == _UNTIL_DATE_LEN:
            day = datetime.strptime(text, "%Y%m%d").date()
            if all_day:
                return day
            return localize(datetime.combine(day, time(23, 59, 59)), tz)
        if len(text) == _UNTIL_DATETIME_LEN and text.endswith("Z"):
            stamp = datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            return stamp.astimezone(tz).date() if all_day else stamp
    except ValueError:
        pass
    raise bad("UNTIL")


def _fmt_until(until: datetime | date) -> str:
    if isinstance(until, datetime):
        return until.strftime("%Y%m%dT%H%M%SZ")
    return until.strftime("%Y%m%d")


def _fmt_byday(byday: ByDay) -> str:
    return ",".join(f"{o if o is not None else ''}{WEEKDAYS[d]}" for d, o in byday)


def _normalise(parts: Parts, until: datetime | date | None) -> str:
    out = [f"FREQ={parts.freq}"]
    if parts.interval != 1:
        out.append(f"INTERVAL={parts.interval}")
    if parts.count is not None:
        out.append(f"COUNT={parts.count}")
    if until is not None:
        out.append(f"UNTIL={_fmt_until(until)}")
    if parts.bymonth:
        out.append("BYMONTH=" + ",".join(map(str, parts.bymonth)))
    if parts.bymonthday:
        out.append("BYMONTHDAY=" + ",".join(map(str, parts.bymonthday)))
    if parts.byday:
        out.append("BYDAY=" + _fmt_byday(parts.byday))
    if parts.bysetpos:
        out.append("BYSETPOS=" + ",".join(map(str, parts.bysetpos)))
    if parts.wkst is not None:
        out.append(f"WKST={WEEKDAYS[parts.wkst]}")
    return ";".join(out)


def parse(text: str, *, all_day: bool, timezone: str) -> Rule:
    """The allow-listed, normalised rule. Raises :class:`InvalidRule`."""
    parts = parse_parts(text)
    until = None
    if parts.until_text is not None:
        until = _parse_until(parts.until_text, all_day=all_day, tz=ZoneInfo(timezone))
    return Rule(
        text=_normalise(parts, until),
        freq=parts.freq,
        count=parts.count,
        until=until,
        interval=parts.interval,
        bymonth=parts.bymonth,
        bymonthday=parts.bymonthday,
        byday=parts.byday,
        bysetpos=parts.bysetpos,
        wkst=parts.wkst,
    )


def until_local(rule: Rule, tz: ZoneInfo) -> datetime | None:
    """A naive local upper bound for walking up to the rule's own ``UNTIL``, or
    ``None``. A timed ``UNTIL`` is an instant, so this is up to a day late: filter
    exactly with :func:`within_until`."""
    if rule.until is None:
        return None
    if isinstance(rule.until, datetime):
        return rule.until.astimezone(tz).replace(tzinfo=None) + _UNTIL_MARGIN
    return datetime.combine(rule.until, time(23, 59, 59))


def within_until(rule: Rule, start_local: datetime, tz: ZoneInfo) -> bool:
    """Is the naive local start at or before the rule's own ``UNTIL``?"""
    if rule.until is None:
        return True
    if isinstance(rule.until, datetime):
        return localize(start_local, tz) <= rule.until
    return start_local.date() <= rule.until


def add_years(value: datetime, years: int) -> datetime:
    """``value`` plus whole years; 29 February lands on 28 February in a common year."""
    year = min(value.year + years, _MAX_YEAR)
    try:
        return value.replace(year=year)
    except ValueError:
        return value.replace(year=year, day=28)


def local_start(span: Span, tz: ZoneInfo, *, all_day: bool) -> datetime:
    """The series' first start as a naive local time (an all-day one: its date at 00:00)."""
    if all_day:
        return datetime.combine(all_day_dates(span, tz.key)[0], time.min)
    return span.starts_at.astimezone(tz).replace(tzinfo=None)


def _instance_end(start_local: datetime, span: Span, *, all_day: bool, tz: ZoneInfo) -> datetime:
    """UTC end of the instance starting at the naive local ``start_local``."""
    if all_day:
        first, after = all_day_dates(span, tz.key)
        return localize(datetime.combine(start_local.date() + (after - first), time.min), tz)
    return localize(start_local, tz) + (span.ends_at - span.starts_at)


def _until_errors(rule: Rule, dtstart: datetime, horizon: datetime, tz: ZoneInfo) -> None:
    until = rule.until
    if until is None:
        return
    if isinstance(until, datetime):
        before, after = until < localize(dtstart, tz), until > localize(horizon, tz)
    else:
        before, after = until < dtstart.date(), until > horizon.date()
    if before:
        raise bad("UNTIL", "before the start")
    if after:
        raise bad("UNTIL", f"more than {constants.RRULE_MAX_YEARS} years after the start")


def validate(rule: Rule, span: Span, *, all_day: bool, timezone: str) -> datetime | None:
    """Check the rule against its event's start and return ``recurrence_until`` (UTC
    end of the last occurrence), ``None`` for an endless rule.

    ``start_not_in_rule`` unless the start is the rule's first occurrence. ``COUNT``
    counts every date the rule names; a date that does not exist locally (a whole day
    skipped by a zone) is counted but has no instance, and the end returned is the
    last one that has."""
    tz = ZoneInfo(timezone)
    dtstart = local_start(span, tz, all_day=all_day)
    horizon = add_years(dtstart, constants.RRULE_MAX_YEARS)
    _until_errors(rule, dtstart, horizon, tz)
    bound = until_local(rule, tz) or horizon
    hits = iterate(rule, dtstart_local=dtstart, lower_local=dtstart, until_local=bound)
    first = next(hits, None)
    if first != dtstart:
        raise InvalidRule(constants.START_NOT_IN_RULE_DETAIL, code=constants.START_NOT_IN_RULE_CODE)
    if rule.count is None and rule.until is None:
        return None  # endless
    last, seen = first, 1
    for hit in hits:
        if seen == rule.count or not within_until(rule, hit, tz):
            break
        seen += 1
        if day_exists(hit.date(), tz):
            last = hit
    if rule.count is not None and seen < rule.count:
        raise bad("COUNT", f"fewer than COUNT occurrences within {constants.RRULE_MAX_YEARS} years")
    return _instance_end(last, span, all_day=all_day, tz=tz)
