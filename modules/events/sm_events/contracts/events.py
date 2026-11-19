"""Domain events other modules can subscribe to.

They are dataclasses on the framework's :class:`~simple_module_core.events.Event`
(a plain, non-frozen dataclass base, so these are too) and carry identifiers and
the few instants a subscriber can act on without a second query: never a title,
a description or any other content.

**Delivery.** Every event is published *in process* after the commit
(:mod:`sm_events.content.bus`): a write that rolls back, or loses the
``expected_revision`` race, publishes nothing, and the handler runs inside the
tenant the event describes. When the host has a durable transport (the
``background_tasks`` outbox) and the event type has durable handlers, it is also
written to the outbox **in the writer's own transaction** (no event for a rolled-back
write, none lost after a commit) and delivered at least once by a worker, with the
framework's retries, backoff and dead-letter state. The scheduled-publish beat publishes
through the same two paths on the worker's bus, so a scheduled publish reaches *durable*
subscribers; an in-process subscriber sees web-process changes only. A handler that raises
never rolls back the writer. The outbox does not promise order between two events of one
``event_id``: a handler that cares re-reads the event instead of trusting the order.

**Subscribing.** ``bus.subscribe_durable(Type, handler, name="<stable name>")`` in your module's
``register_event_handlers``, *before* any ``if app is None: return`` (the worker calls it with
``app=None``), sees everything; ``bus.subscribe`` sees web-process changes only. Never rename
a durable handler. Delivery is at-least-once: make the handler idempotent (the ``event_id`` and
the instants in the payload are the natural keys).

**Payloads** are plain dataclasses of identifiers and instants (``check_serializable`` accepts
them): never a title, a description, personal data or a type's ``extra``.

Only events that are, or were, published are announced; a draft changes silently. A write
covered by a specific event emits only that one (a published reschedule is
``EventRescheduled``, not also ``EventUpdated``). Every event carries ``tenant_id``,
``event_id``, ``calendar_id`` and ``uid``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from simple_module_core.events import Event

__all__ = [
    "EventCancelled",
    "EventDeleted",
    "EventPublished",
    "EventReinstated",
    "EventRescheduled",
    "EventRestored",
    "EventUnpublished",
    "EventUpdated",
    "OccurrenceSkipped",
]


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


@dataclass
class EventUnpublished(Event):
    """A published event went back to draft (``was_scheduled`` false), or a scheduled publish
    was cancelled (``was_scheduled`` true)."""

    tenant_id: str
    event_id: uuid.UUID
    calendar_id: uuid.UUID
    uid: str
    was_scheduled: bool


@dataclass
class EventReinstated(Event):
    """A cancellation was undone: the event's ``cancelled`` flag was cleared
    (``original_start`` is ``None``), or one occurrence's cancelled override was cleared or
    replaced by another kind (``original_start`` is that occurrence's original UTC start)."""

    tenant_id: str
    event_id: uuid.UUID
    calendar_id: uuid.UUID
    uid: str
    original_start: datetime | None


@dataclass
class OccurrenceSkipped(Event):
    """One occurrence of a published series was skipped."""

    tenant_id: str
    event_id: uuid.UUID
    calendar_id: uuid.UUID
    uid: str
    original_start: datetime


@dataclass
class EventRestored(Event):
    """A published event came back from the trash."""

    tenant_id: str
    event_id: uuid.UUID
    calendar_id: uuid.UUID
    uid: str


@dataclass
class EventUpdated(Event):
    """Any other write to a published event. ``changed`` is the sorted top-level names that
    changed (``texts``, ``venue_name``, ``category_id``, ``extra``, ...): names, never values."""

    tenant_id: str
    event_id: uuid.UUID
    calendar_id: uuid.UUID
    uid: str
    changed: tuple[str, ...]
