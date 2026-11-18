"""Domain events other modules can subscribe to.

They are dataclasses on the framework's :class:`~simple_module_core.events.Event`
(a plain, non-frozen dataclass base, so these are too) and carry identifiers and
the few instants a subscriber can act on without a second query: never a title,
a description or any other content.

**They are published after the commit**, from the request layer
(:mod:`sm_events.content.bus`): a write that rolls back, or loses the
``expected_revision`` race, publishes nothing. The event is published inside the
tenant it describes, so a handler finds that tenant bound. **A worker publishes
nothing by itself**: the scheduled-publish task builds its own bus.

Only events that are, or were, published are announced; a draft changes silently.
Reinstating, unpublishing and skipping an occurrence emit nothing yet.
Every event carries ``tenant_id``, ``event_id``, ``calendar_id`` and ``uid``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from simple_module_core.events import Event

__all__ = ["EventCancelled", "EventDeleted", "EventPublished", "EventRescheduled"]


@dataclass
class EventPublished(Event):
    """The event went live (approved now, or its scheduled time came)."""

    tenant_id: str
    event_id: uuid.UUID
    calendar_id: uuid.UUID
    uid: str
    published_at: datetime


@dataclass
class EventRescheduled(Event):
    """A published event's time, timezone, all-day flag or rule changed, or one
    occurrence moved.

    ``original_start`` is ``None`` for a change to the whole event or series and
    the occurrence's original UTC start for a moved occurrence. ``old_*`` and
    ``new_*`` are the master's UTC instants (the moved occurrence's own, for a
    move). ``rule_changed`` is true when the recurrence rule changed."""

    tenant_id: str
    event_id: uuid.UUID
    calendar_id: uuid.UUID
    uid: str
    original_start: datetime | None
    old_start: datetime
    old_end: datetime
    new_start: datetime
    new_end: datetime
    rule_changed: bool


@dataclass
class EventCancelled(Event):
    """The event was cancelled (``original_start`` is ``None``), or one of its
    occurrences was (``original_start`` is that occurrence's original UTC start)."""

    tenant_id: str
    event_id: uuid.UUID
    calendar_id: uuid.UUID
    uid: str
    original_start: datetime | None


@dataclass
class EventDeleted(Event):
    """The event was trashed. ``was_published`` is true when it was live."""

    tenant_id: str
    event_id: uuid.UUID
    calendar_id: uuid.UUID
    uid: str
    was_published: bool
