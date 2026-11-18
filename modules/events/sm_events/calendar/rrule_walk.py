"""Walking a rule's naive local starts, in work bounded by the span asked for. Pure.

**Every iteration has a stop.** dateutil checks ``until`` only when it has a
candidate, so a sparse rule (29 February on a Monday, next in 2044) keeps scanning
past the window until its next match, and a rule that can never match runs on to
year 9999. This module never lets that happen:

* ``DAILY`` and ``WEEKLY`` rules are walked here, day by day or week by week, from
  the period holding the lower bound to ``until`` and not one period further. The
  work is the length of the span, whatever the rule matches. A test compares the
  result with plain dateutil for every allowed shape.
* ``MONTHLY`` and ``YEARLY`` periods are coarse, so dateutil does the work but
  starts at the period nearest the lower bound, and the whole problem is shifted by
  a multiple of 400 years (the Gregorian cycle: same weekdays, same leap years) so
  that a walk to year 9999 is a few hundred periods at most.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from dateutil import rrule as du

if TYPE_CHECKING:
    from sm_events.calendar.rrule import Rule

__all__ = ["build", "iterate"]

_DU_FREQ = {
    "DAILY": du.DAILY,
    "WEEKLY": du.WEEKLY,
    "MONTHLY": du.MONTHLY,
    "YEARLY": du.YEARLY,
}
_CYCLE_YEARS = 400
_TARGET_YEAR = 9900  # where a shifted walk puts ``until``
_DAYS_PER_WEEK = 7


def _kwargs(rule: Rule, dtstart: datetime) -> dict[str, Any]:
    """dateutil's keyword arguments, with its dtstart-derived defaults made explicit
    so that moving ``dtstart`` along the rule's own period cannot change them."""
    bymonth, bymonthday = rule.bymonth, rule.bymonthday
    byweekday = [du.weekday(d, o) if o is not None else du.weekday(d) for d, o in rule.byday]
    if not (bymonthday or byweekday):
        if rule.freq == "YEARLY":
            bymonth = bymonth or (dtstart.month,)
            bymonthday = (dtstart.day,)
        elif rule.freq == "MONTHLY":
            bymonthday = (dtstart.day,)
        elif rule.freq == "WEEKLY":
            byweekday = [du.weekday(dtstart.weekday())]
    return {
        "freq": _DU_FREQ[rule.freq],
        "interval": rule.interval,
        "wkst": rule.wkst if rule.wkst is not None else 0,
        "bymonth": bymonth or None,
        "bymonthday": bymonthday or None,
        "byweekday": byweekday or None,
        "bysetpos": rule.bysetpos or None,
    }


def build(rule: Rule, *, dtstart_local: datetime, until_local: datetime | None) -> du.rrule:
    """The dateutil rule on a naive local ``dtstart``: ``COUNT`` dropped, ``until``
    always set (an endless rule is bounded by the caller's window)."""
    if until_local is None:
        raise ValueError("an rrule is never iterated without an until")
    return du.rrule(dtstart=dtstart_local, until=until_local, **_kwargs(rule, dtstart_local))


@dataclass(frozen=True)
class _Days:
    """Which days a rule's ``BY`` parts admit (dateutil ignores ordinals below MONTHLY)."""

    months: frozenset[int]
    monthdays: frozenset[int]
    weekdays: frozenset[int]

    @classmethod
    def of(cls, kwargs: dict[str, Any]) -> _Days:
        return cls(
            frozenset(kwargs["bymonth"] or ()),
            frozenset(kwargs["bymonthday"] or ()),
            frozenset(w.weekday for w in kwargs["byweekday"] or ()),
        )

    def admits(self, day: date) -> bool:
        if self.months and day.month not in self.months:
            return False
        if self.monthdays:
            length = calendar.monthrange(day.year, day.month)[1]
            if day.day not in self.monthdays and day.day - length - 1 not in self.monthdays:
                return False
        return not self.weekdays or day.weekday() in self.weekdays


def _positions(days: list[date], bysetpos: tuple[int, ...]) -> list[date]:
    """dateutil's ``BYSETPOS`` over one period's admitted days."""
    picked: set[date] = set()
    for pos in bysetpos:
        index = pos - 1 if pos > 0 else pos
        if -len(days) <= index < len(days):
            picked.add(days[index])
    return sorted(picked)


def _daily(
    rule: Rule, kwargs: dict[str, Any], dtstart: datetime, lower: datetime, until: datetime
) -> Iterator[datetime]:
    days, step = _Days.of(kwargs), timedelta(days=rule.interval)
    keep = not rule.bysetpos or 1 in rule.bysetpos or -1 in rule.bysetpos  # one day a period
    tod = dtstart.time().replace(microsecond=0)
    first = max(lower.date(), dtstart.date())
    first += timedelta(days=-(first - dtstart.date()).days % rule.interval)
    last = until.date()
    day = first
    while day <= last:
        if keep and days.admits(day):
            hit = datetime.combine(day, tod)
            if hit > until:
                return
            if hit >= lower and hit >= dtstart:
                yield hit
        if last - day < step:
            return
        day += step


def _weekly(
    rule: Rule, kwargs: dict[str, Any], dtstart: datetime, lower: datetime, until: datetime
) -> Iterator[datetime]:
    days, wkst = _Days.of(kwargs), kwargs["wkst"]
    begin = dtstart.date()
    base = begin - timedelta(days=(begin.weekday() - wkst) % _DAYS_PER_WEEK)
    week = max(0, (lower.date() - base).days // _DAYS_PER_WEEK)
    week -= week % rule.interval
    tod, last = dtstart.time().replace(microsecond=0), until.date()
    while base + timedelta(weeks=week) <= last:
        wstart = base + timedelta(weeks=week)
        # The first period starts at dtstart's own day, as dateutil's does.
        found = [
            d
            for d in (wstart + timedelta(days=i) for i in range(_DAYS_PER_WEEK))
            if d >= begin and days.admits(d)
        ]
        for day in _positions(found, rule.bysetpos) if rule.bysetpos else found:
            hit = datetime.combine(day, tod)
            if hit > until:
                return
            if hit >= lower and hit >= dtstart:
                yield hit
        week += rule.interval


def _aligned_start(rule: Rule, dtstart: datetime, lower: datetime) -> datetime:
    """The start of the last period, in the rule's own phase, at or before ``lower``
    (``MONTHLY`` and ``YEARLY``)."""
    if lower <= dtstart:
        return dtstart
    step, tod = rule.interval, dtstart.time()
    if rule.freq == "MONTHLY":
        months = (lower.year - dtstart.year) * 12 + lower.month - dtstart.month
        months = months // step * step
        if months <= 0:
            return dtstart
        index = dtstart.year * 12 + dtstart.month - 1 + months
        return datetime.combine(date(index // 12, index % 12 + 1, 1), tod)
    years = (lower.year - dtstart.year) // step * step
    if years <= 0:
        return dtstart
    return datetime.combine(date(dtstart.year + years, 1, 1), tod)


def _coarse(
    rule: Rule, kwargs: dict[str, Any], dtstart: datetime, lower: datetime, until: datetime
) -> Iterator[datetime]:
    start = _aligned_start(rule, dtstart, lower)
    if until < start:
        return
    shift = _CYCLE_YEARS * ((_TARGET_YEAR - until.year) // _CYCLE_YEARS)
    walker = du.rrule(
        dtstart=start.replace(year=start.year + shift),
        until=until.replace(year=until.year + shift),
        **kwargs,
    )
    for hit in walker:
        value = hit.replace(year=hit.year - shift)
        if value >= lower:
            yield value


def iterate(
    rule: Rule, *, dtstart_local: datetime, lower_local: datetime, until_local: datetime
) -> Iterator[datetime]:
    """Naive local starts in ``[lower_local, until_local]``, ascending, never beyond
    ``until_local``, and in work bounded by the span asked for (see module docs)."""
    kwargs = _kwargs(rule, dtstart_local)
    walk = {"DAILY": _daily, "WEEKLY": _weekly}.get(rule.freq, _coarse)
    try:
        yield from walk(rule, kwargs, dtstart_local, lower_local, until_local)
    except OverflowError:  # a date past year 9999: nothing more to yield
        return
