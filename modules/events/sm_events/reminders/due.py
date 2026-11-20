"""When a reminder is due. Pure: instants in, instants out; no database, no clock, no zone.

A reminder for an occurrence starting at ``start`` with lead ``L`` is due at ``start - L``, an
exact duration in UTC. The occurrence's start is whatever the module's own occurrences read
returns (a series' instance, a moved occurrence at its *new* time, an all-day event at local
midnight of **its** zone, a DST gap shifted forward and a fold taken once), so this module has no
recurrence engine of its own. Consequences, pinned by the tests across the 2026-2027 clock
changes of Vienna, New York and Lord Howe: a one-day lead is exactly 24 hours, so its wall-clock
time differs by an hour (30 minutes in Lord Howe) when a change falls in between.

A tick at ``now`` sends a reminder when ``now - catchup(L) <= due < now + EARLY`` and the
occurrence has not started. ``EARLY`` is one beat, so a punctual tick is never late and at most
one tick early; ``catchup`` is how late a reminder may still be (a missed tick must not produce
a flood, and a late reminder is worthless). Later than that it is **stale**: never sent, and
recomputed and refused again on every tick until it leaves the window. A follow created too late
for a lead, or an event edited so that the new due time is already past, therefore sends nothing
for that occurrence and lead; at most one reminder is ever sent for a ``(follow, occurrence,
start, lead)``, which the ledger's key guarantees.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from sm_events.core.constants.reminders_limits import REMINDER_CATCHUP, REMINDER_EARLY

__all__ = ["due_at", "is_due", "is_stale", "next_due", "start_window"]


def due_at(start: datetime, lead: int) -> datetime:
    return start - timedelta(minutes=lead)


def start_window(now: datetime, lead: int) -> tuple[datetime, datetime]:
    """``[lo, hi)``: the starts whose reminder for ``lead`` is due at ``now``. At most six
    hours and a minute wide, which bounds every read made for it."""
    lead_span = timedelta(minutes=lead)
    return now + lead_span - REMINDER_CATCHUP[lead], now + lead_span + REMINDER_EARLY


def is_due(*, start: datetime, lead: int, now: datetime) -> bool:
    lo, hi = start_window(now, lead)
    return lo <= start < hi and now < start


def is_stale(*, start: datetime, lead: int, now: datetime) -> bool:
    """Past the catch-up, or the occurrence has started: never sent."""
    return start <= now or due_at(start, lead) < now - REMINDER_CATCHUP[lead]


def next_due(starts: Iterable[datetime], lead: int, now: datetime) -> datetime | None:
    """When the next reminder for ``lead`` is due, among ``starts`` (ascending); ``None`` when
    none is. Stale ones are skipped (too late for the next occurrence). Stops at the first
    answer, so an endless series is never walked."""
    for start in starts:
        if not is_stale(start=start, lead=lead, now=now):
            return due_at(start, lead)
    return None
