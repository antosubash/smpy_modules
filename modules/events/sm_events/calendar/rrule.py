"""RRULE: parse, validate, normalise, derive ``recurrence_until``, and iterate. Pure.

Only an allow-list of parts is accepted (:mod:`sm_events.calendar.rrule_parts`) and
dateutil only ever sees keyword arguments built from it, never raw text.

Iteration lives in :mod:`sm_events.calendar.rrule_walk`: every walk has a stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sm_events.calendar.rrule_parts import WEEKDAYS, ByDay, Parts, bad, parse_parts
from sm_events.calendar.rrule_walk import build, iterate
from sm_events.calendar.times import Span, all_day_dates, localize
from sm_events.core import constants
from sm_events.core.errors import InvalidRule

__all__ = ["Rule", "build", "iterate", "parse", "until_local", "validate"]

_UNTIL_DATE_LEN = 8
_UNTIL_DATETIME_LEN = 16


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
    """The rule's own ``UNTIL`` as a naive local bound (inclusive), or ``None``."""
    if rule.until is None:
        return None
    if isinstance(rule.until, datetime):
        return rule.until.astimezone(tz).replace(tzinfo=None)
    return datetime.combine(rule.until, time(23, 59, 59))


def _local_start(span: Span, tz: ZoneInfo) -> datetime:
    return span.starts_at.astimezone(tz).replace(tzinfo=None)


def _instance_end(start_local: datetime, span: Span, *, all_day: bool, tz: ZoneInfo) -> datetime:
    """UTC end of the instance starting at the naive local ``start_local``."""
    if all_day:
        first, after = all_day_dates(span, tz.key)
        return localize(datetime.combine(start_local.date() + (after - first), time.min), tz)
    return localize(start_local, tz) + (span.ends_at - span.starts_at)


def validate(rule: Rule, span: Span, *, all_day: bool, timezone: str) -> datetime | None:
    """Check the rule against its event's start and return ``recurrence_until`` (UTC
    end of the last occurrence), ``None`` for an endless rule.

    ``start_not_in_rule`` unless the start is the rule's first occurrence."""
    tz = ZoneInfo(timezone)
    dtstart = _local_start(span, tz)
    horizon = dtstart.replace(year=dtstart.year + constants.RRULE_MAX_YEARS)
    until = until_local(rule, tz)
    if until is not None:
        if until < dtstart:
            raise bad("UNTIL", "before the start")
        if until > horizon:
            raise bad("UNTIL", f"more than {constants.RRULE_MAX_YEARS} years after the start")
    bound = until if until is not None else horizon
    hits = iterate(rule, dtstart_local=dtstart, lower_local=dtstart, until_local=bound)
    first = next(hits, None)
    if first != dtstart:
        raise InvalidRule(constants.START_NOT_IN_RULE_DETAIL, code=constants.START_NOT_IN_RULE_CODE)
    if rule.count is None and rule.until is None:
        return None  # endless
    last, seen = first, 1
    for hit in hits:
        if seen == rule.count:
            break
        last, seen = hit, seen + 1
    if rule.count is not None and seen < rule.count:
        raise bad("COUNT", f"fewer than COUNT occurrences within {constants.RRULE_MAX_YEARS} years")
    return _instance_end(last, span, all_day=all_day, tz=tz)
