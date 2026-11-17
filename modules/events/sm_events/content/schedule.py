"""An event's schedule: span, timezone, all-day flag and recurrence, as one value.

Built from what a request sent (local wall clock) and bounded by
:mod:`sm_events.calendar.times` and :mod:`sm_events.calendar.rrule`. A series'
``recurrence_until`` is derived here every time, never taken from the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sm_events.calendar import rrule
from sm_events.calendar.times import Span, to_local, to_span
from sm_events.models import Event
from sm_events.web.schemas.events_in import TimesIn

__all__ = ["Schedule", "build", "of_event", "patched"]


@dataclass(frozen=True)
class Schedule:
    span: Span
    all_day: bool
    timezone: str
    rrule: str | None
    recurrence_until: datetime | None

    @property
    def recurring(self) -> bool:
        return self.rrule is not None


def _make(*, all_day: bool, timezone: str, start: str, end: str, rule_text: str | None) -> Schedule:
    recurring = bool(rule_text)
    span = to_span(all_day=all_day, timezone=timezone, start=start, end=end, recurring=recurring)
    if not rule_text:
        return Schedule(span, all_day, timezone, None, None)
    rule = rrule.parse(rule_text, all_day=all_day, timezone=timezone)
    until = rrule.validate(rule, span, all_day=all_day, timezone=timezone)
    return Schedule(span, all_day, timezone, rule.text, until)


def build(times: TimesIn, rule_text: str | None) -> Schedule:
    """A new event's schedule. ``InvalidTimes`` / ``InvalidRule``."""
    return _make(
        all_day=times.all_day,
        timezone=times.timezone,
        start=times.start,
        end=times.end,
        rule_text=rule_text or None,
    )


def of_event(event: Event) -> Schedule:
    """What is stored, unchanged."""
    return Schedule(
        Span(event.starts_at, event.ends_at),
        event.all_day,
        event.timezone,
        event.rrule,
        event.recurrence_until,
    )


def patched(event: Event, *, times: TimesIn | None, rule: str | None, rule_set: bool) -> Schedule:
    """The schedule after a PATCH that sent ``times`` and/or ``rrule``. Whichever
    is left out is taken from the event, and everything is bounded and the rule
    checked again, because each depends on the other (the duration limit on
    recurrence, an ``UNTIL`` on the all-day flag and the zone)."""
    if times is not None:
        all_day, timezone, start, end = times.all_day, times.timezone, times.start, times.end
    else:
        all_day, timezone = event.all_day, event.timezone
        start, end = to_local(
            Span(event.starts_at, event.ends_at), all_day=all_day, timezone=timezone
        )
    rule_text = (rule if rule_set else event.rrule) or None
    return _make(all_day=all_day, timezone=timezone, start=start, end=end, rule_text=rule_text)
