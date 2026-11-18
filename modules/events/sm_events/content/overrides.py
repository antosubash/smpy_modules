"""Overrides: skip, cancel or move one occurrence of a series.

* Only a recurring event takes one (``not_recurring``), and only for an
  ``original_start`` that really is an occurrence of its current rule
  (``not_an_occurrence``); a second write for the same instant replaces the first.
* ``moved`` may change only the start and the end, within the series' duration
  bound, and may move anywhere in time. Title, place and category are the whole
  series' business.
* Like every write: the stale guard first, a savepoint around everything, a
  revision row, and, for a live event, a bus event after the commit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import select

from sm_events.calendar import rrule
from sm_events.calendar.expand import Instance, instances
from sm_events.calendar.times import Span, to_span
from sm_events.content import bus, notices, revisions
from sm_events.content.guard import Unchanged, claim
from sm_events.core.access.events import load_event, require
from sm_events.core.errors import NotAnOccurrence, NotFound, NotRecurring
from sm_events.models import Event, OccurrenceOverride, OverrideKind
from sm_events.web.schemas.overrides import OverrideIn

__all__ = ["clear_override", "set_override"]

_TICK = timedelta(microseconds=1)


def _instance(event: Event, original_start: datetime) -> Instance:
    """The occurrence starting exactly at ``original_start``; ``NotAnOccurrence``
    when the rule has none there."""
    rule = rrule.parse(event.rrule or "", all_day=event.all_day, timezone=event.timezone)
    found = instances(
        rule=rule,
        span=Span(event.starts_at, event.ends_at),
        all_day=event.all_day,
        timezone=event.timezone,
        window_start=original_start,
        window_end=original_start + _TICK,
        recurrence_until=event.recurrence_until,
    )
    for item in found:
        if item.original_start == original_start:
            return item
    raise NotAnOccurrence


async def _existing(
    db: Any, event_id: uuid.UUID, original_start: datetime
) -> OccurrenceOverride | None:
    return (
        await db.execute(
            select(OccurrenceOverride).where(
                OccurrenceOverride.event_id == event_id,
                OccurrenceOverride.original_start == original_start,
            )
        )
    ).scalar_one_or_none()


async def set_override(
    db: Any, who: ResourcePrincipal, event_id: uuid.UUID, data: OverrideIn
) -> OccurrenceOverride:
    """Write one override. Repeating the stored one writes nothing and emits nothing
    (the same revision, no history row); a re-move reports the slot it was moved *from*
    (the previous move) as ``old``."""
    event, rights = await load_event(db, who, event_id)
    require(rights)
    try:
        return await _write(db, who, event, data)
    except Unchanged as same:
        await db.refresh(event)  # the savepoint rolled back: the stored revision
        await db.refresh(same.row)
        return same.row


async def _write(
    db: Any, who: ResourcePrincipal, event: Event, data: OverrideIn
) -> OccurrenceOverride:
    async with db.begin_nested():
        await claim(db, event, data.expected_revision, actor=who.user_id)
        if event.rrule is None:
            raise NotRecurring
        original = data.original_start.astimezone(UTC)
        instance = _instance(event, original)
        moved = data.kind == OverrideKind.MOVED.value
        span = (
            to_span(
                all_day=event.all_day,
                timezone=event.timezone,
                start=data.start or "",
                end=data.end or "",
                recurring=True,
            )
            if moved
            else None
        )
        row = await _existing(db, event.id, original)
        new = (span.starts_at, span.ends_at) if span else (None, None)
        if row is not None and (row.kind, row.note, row.starts_at, row.ends_at) == (
            data.kind,
            data.note,
            *new,
        ):
            raise Unchanged(row)
        was_cancelled = row is not None and row.kind == OverrideKind.CANCELLED.value
        before = (instance.start, instance.end)
        if row is None:
            row = OccurrenceOverride(event_id=event.id, original_start=original, kind=data.kind)
            db.add(row)
        elif row.kind == OverrideKind.MOVED.value and row.starts_at and row.ends_at:
            before = (row.starts_at, row.ends_at)  # a re-move leaves the previous slot
        row.kind, row.note = data.kind, data.note
        row.starts_at, row.ends_at = new
        await db.flush()
        await revisions.record(db, event, action="override_set", actor=who.user_id)
        if span is not None:
            bus.emit(
                db,
                notices.rescheduled(
                    event, original_start=original, old=before, new=(span.starts_at, span.ends_at)
                ),
            )
        elif data.kind == OverrideKind.CANCELLED.value and not was_cancelled:
            bus.emit(db, notices.cancelled(event, original_start=original))
    return row


async def clear_override(
    db: Any, who: ResourcePrincipal, event_id: uuid.UUID, override_id: int, expected: int
) -> None:
    """Remove one override. ``NotFound`` for an id that is not this event's."""
    event, rights = await load_event(db, who, event_id)
    require(rights)
    async with db.begin_nested():
        await claim(db, event, expected, actor=who.user_id)
        row = (
            await db.execute(
                select(OccurrenceOverride).where(
                    OccurrenceOverride.id == override_id, OccurrenceOverride.event_id == event.id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFound
        await db.delete(row)
        await db.flush()
        await revisions.record(db, event, action="override_cleared", actor=who.user_id)
