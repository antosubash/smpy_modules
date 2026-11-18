"""Which occurrence of an event a public page shows.

An occurrence's address is ``{slug}?date=YYYY-MM-DD``: the local date of its original start in the
event's timezone (an all-day one: its first date). Rules are at most daily, so one local date names
at most one occurrence. A moved occurrence keeps its original date in the address and shows its new
time; a cancelled one is shown, marked; a skipped one, a date that is not an occurrence, a date
outside the years a calendar means, an unparsable date and ``?date=`` on a one-off are the 404.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from sm_events.calendar import rrule
from sm_events.calendar.expand import Instance, instances
from sm_events.calendar.times import Span, all_day_dates, localize
from sm_events.core import constants
from sm_events.core.errors import InvalidRule
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Event, OccurrenceOverride, OverrideKind

__all__ = [
    "ShownOccurrence",
    "next_occurrences",
    "own_occurrence",
    "parse_date_param",
    "shown_occurrence",
]

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ONE_DAY = timedelta(days=1)
Invalid = Literal["invalid"]


@dataclass(frozen=True)
class ShownOccurrence:
    """One occurrence as a page shows it. ``end_date`` is exclusive, like the occurrences read's."""

    start: datetime
    end: datetime
    all_day: bool
    start_date: date | None
    end_date: date | None
    status: Literal["scheduled", "cancelled", "rescheduled"]
    previous_start: datetime | None
    date_param: date | None


def parse_date_param(raw: str | None) -> date | Invalid | None:
    """``None`` when no ``?date=`` was sent, the date, or ``"invalid"`` (not ``YYYY-MM-DD``, not a
    real date, or outside the supported years)."""
    if raw is None:
        return None
    if not _DATE.fullmatch(raw):
        return "invalid"
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return "invalid"
    if not constants.ORIGINAL_START_MIN_YEAR <= day.year <= constants.ORIGINAL_START_MAX_YEAR:
        return "invalid"
    return day


def _rule(event: Event) -> rrule.Rule | None:
    if not event.rrule:
        return None
    try:
        return rrule.parse(event.rrule, all_day=event.all_day, timezone=event.timezone)
    except InvalidRule:
        return None


def _instances(
    event: Event, rule: rrule.Rule, start: datetime, end: datetime
) -> Iterable[Instance]:
    return instances(
        rule=rule,
        span=Span(event.starts_at, event.ends_at),
        all_day=event.all_day,
        timezone=event.timezone,
        window_start=start,
        window_end=end,
        recurrence_until=event.recurrence_until,
    )


def _shown(
    event: Event, inst: Instance, change: OccurrenceOverride | None, day: date | None
) -> ShownOccurrence | None:
    """The instance as a page shows it, or ``None`` for a skipped one."""
    kind = change.kind if change is not None else None
    if kind == OverrideKind.SKIPPED.value:
        return None
    start, end, status, previous = inst.start, inst.end, "scheduled", None
    if (
        change is not None
        and kind == OverrideKind.MOVED.value
        and change.starts_at is not None
        and change.ends_at is not None
    ):
        start, end, status, previous = (
            change.starts_at,
            change.ends_at,
            "rescheduled",
            inst.original_start,
        )
    elif kind == OverrideKind.CANCELLED.value:
        status = "cancelled"
    first = after = None
    if event.all_day:
        first, after = all_day_dates(Span(start, end), event.timezone)
    return ShownOccurrence(
        start=start,
        end=end,
        all_day=event.all_day,
        start_date=first,
        end_date=after,
        status=status,  # type: ignore[arg-type]
        previous_start=previous,
        date_param=day,
    )


def _local_day(event: Event, inst: Instance) -> date:
    return inst.original_start.astimezone(ZoneInfo(event.timezone)).date()


async def shown_occurrence(db: Any, event: Event, day: date) -> ShownOccurrence | None:
    """The occurrence of a series addressed by ``day``, or ``None`` for the 404: a one-off, a
    date that is not an instance, a skipped instance."""
    rule = _rule(event)
    if rule is None:
        return None
    tz = ZoneInfo(event.timezone)
    start = localize(datetime.combine(day, time.min), tz)
    end = localize(datetime.combine(day + _ONE_DAY, time.min), tz)
    found = next(
        (i for i in _instances(event, rule, start, end) if _local_day(event, i) == day), None
    )
    if found is None:
        return None
    stmt = select(OccurrenceOverride).where(
        OccurrenceOverride.tenant_id == bound_tenant(),  # type: ignore[arg-type]
        OccurrenceOverride.event_id == event.id,
        OccurrenceOverride.original_start == found.original_start,
    )
    change = (await db.execute(stmt)).scalars().first()
    return _shown(event, found, change, day)


def next_occurrences(
    event: Event, overrides: Iterable[OccurrenceOverride], *, now: datetime, limit: int
) -> list[ShownOccurrence]:
    """The next ``limit`` occurrences of a series from ``now`` (within the read's own range),
    skipped ones dropped, moved ones at their new time, cancelled ones marked; by start."""
    rule = _rule(event)
    if rule is None:
        return []
    changes = {o.original_start: o for o in overrides}
    out: list[ShownOccurrence] = []
    for inst in _instances(event, rule, now, now + timedelta(days=constants.MAX_RANGE_DAYS)):
        shown = _shown(event, inst, changes.get(inst.original_start), _local_day(event, inst))
        if shown is not None:
            out.append(shown)
    out.sort(key=lambda o: (o.start, o.end))
    return out[:limit]


def own_occurrence(event: Event) -> ShownOccurrence:
    """A one-off's own span as the one occurrence its page shows."""
    first = after = None
    if event.all_day:
        first, after = all_day_dates(Span(event.starts_at, event.ends_at), event.timezone)
    return ShownOccurrence(
        start=event.starts_at,
        end=event.ends_at,
        all_day=event.all_day,
        start_date=first,
        end_date=after,
        status="cancelled" if event.cancelled else "scheduled",
        previous_start=None,
        date_param=None,
    )
