"""One occurrence of an event, found by its key: the shape a seat counts against.

A one-off has one occurrence, keyed ``"{event_id}"``. A series has one per instance of its rule,
keyed ``"{event_id}:{original start}"`` (PR 2's stable key, UTC, ``YYYYMMDDTHHMMSSZ``), so a moved
occurrence keeps its key and its seats while showing its new time, a cancelled one is marked, and
a skipped one, a date the rule does not have, a stored rule that no longer parses and a key of
another event all resolve to nothing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from sm_events.calendar import rrule
from sm_events.calendar.expand import instances
from sm_events.calendar.times import Span
from sm_events.core import constants
from sm_events.core.errors import InvalidRule
from sm_events.models import Event, OccurrenceOverride, OverrideKind
from sm_events.registration import args

__all__ = ["ResolvedOccurrence", "load_resolved", "original_start_of", "resolve_key"]

_TICK = timedelta(microseconds=1)


@dataclass(frozen=True)
class ResolvedOccurrence:
    key: str
    start: datetime
    end: datetime
    cancelled: bool
    """This occurrence only; the event's own flag is the caller's to read."""
    date_param: date | None
    """The ``?date=`` of its page (the local date of its original start); ``None`` for a one-off."""


def original_start_of(event: Event, key: str) -> datetime | None:
    """The original start a series key names, ``None`` for a key that names no instance shape
    of this event (another event's, the wrong kind for the event, impossible, out of years)."""
    prefix, _, stamp = key.partition(":")
    if prefix != str(event.id):
        return None
    if not stamp:
        return None
    try:
        original = args.parse_stamp(stamp)
    except ValueError:
        return None
    if not constants.ORIGINAL_START_MIN_YEAR <= original.year < constants.ORIGINAL_START_MAX_YEAR:
        return None
    return original


def resolve_key(
    event: Event, overrides: Iterable[OccurrenceOverride], key: str
) -> ResolvedOccurrence | None:
    """The occurrence ``key`` names, with the matching override applied; ``None`` when there is no
    such occurrence. ``overrides`` need hold only the one for this key's original start."""
    if event.rrule is None:
        if key != str(event.id):
            return None
        return ResolvedOccurrence(key, event.starts_at, event.ends_at, False, None)
    original = original_start_of(event, key)
    if original is None:
        return None
    try:
        rule = rrule.parse(event.rrule, all_day=event.all_day, timezone=event.timezone)
    except InvalidRule:
        return None
    found = next(
        (
            inst
            for inst in instances(
                rule=rule,
                span=Span(event.starts_at, event.ends_at),
                all_day=event.all_day,
                timezone=event.timezone,
                window_start=original,
                window_end=original + _TICK,
                recurrence_until=event.recurrence_until,
            )
            if inst.original_start == original
        ),
        None,
    )
    if found is None:
        return None
    start, end, cancelled = found.start, found.end, False
    change = next((o for o in overrides if o.original_start == original), None)
    if change is not None:
        if change.kind == OverrideKind.SKIPPED.value:
            return None
        if change.kind == OverrideKind.CANCELLED.value:
            cancelled = True
        elif change.kind == OverrideKind.MOVED.value and change.starts_at and change.ends_at:
            start, end = change.starts_at, change.ends_at
    day = original.astimezone(ZoneInfo(event.timezone)).date()
    return ResolvedOccurrence(key, start, end, cancelled, day)


async def load_resolved(
    db: Any, event: Event, key: str, *, fresh: bool = False
) -> ResolvedOccurrence | None:
    """:func:`resolve_key` with the one override it needs read from the database; ``fresh`` re-reads
    an override the session already holds (the read under the lock)."""
    original = original_start_of(event, key) if event.rrule is not None else None
    changes: list[OccurrenceOverride] = []
    if original is not None:
        stmt = select(OccurrenceOverride).where(
            OccurrenceOverride.event_id == event.id,
            OccurrenceOverride.original_start == original,
        )
        if fresh:
            stmt = stmt.execution_options(populate_existing=True)
        changes = list((await db.execute(stmt)).scalars().all())
    return resolve_key(event, changes, key)
