"""Builders for the bus events a write announces (see :mod:`sm_events.contracts.events`).

Only an event that is live is announced when it changes, and only one that has
been live is announced when it is trashed; a draft changes silently. Each builder
reads the event's *final* state, so call it after the write.
"""

from __future__ import annotations

from datetime import datetime

from sm_events.content.schedule import Schedule
from sm_events.contracts.events import (
    EventCancelled,
    EventDeleted,
    EventPublished,
    EventRescheduled,
)
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Event
from sm_events.models.enums import EventStatus

__all__ = ["cancelled", "deleted", "published", "rescheduled", "series_changed"]


def _ids(event: Event) -> dict:
    return {
        "tenant_id": bound_tenant(),
        "event_id": event.id,
        "calendar_id": event.calendar_id,
        "uid": event.uid,
    }


def is_live(event: Event) -> bool:
    return event.status == EventStatus.PUBLISHED.value


def published(event: Event, *, at: datetime) -> EventPublished:
    return EventPublished(**_ids(event), published_at=at)


def rescheduled(
    event: Event,
    *,
    original_start: datetime | None,
    old: tuple[datetime, datetime],
    new: tuple[datetime, datetime],
    rule_changed: bool = False,
) -> EventRescheduled | None:
    """``None`` unless the event is live."""
    if not is_live(event):
        return None
    return EventRescheduled(
        **_ids(event),
        original_start=original_start,
        old_start=old[0],
        old_end=old[1],
        new_start=new[0],
        new_end=new[1],
        rule_changed=rule_changed,
    )


def series_changed(event: Event, old: Schedule) -> EventRescheduled | None:
    """The whole event (or series) changed its time, zone, all-day flag or rule."""
    same = (
        old.span.starts_at == event.starts_at
        and old.span.ends_at == event.ends_at
        and old.timezone == event.timezone
        and old.all_day == event.all_day
        and old.rrule == event.rrule
    )
    if same:
        return None
    return rescheduled(
        event,
        original_start=None,
        old=(old.span.starts_at, old.span.ends_at),
        new=(event.starts_at, event.ends_at),
        rule_changed=old.rrule != event.rrule,
    )


def cancelled(event: Event, *, original_start: datetime | None) -> EventCancelled | None:
    """``None`` unless the event is live."""
    if not is_live(event):
        return None
    return EventCancelled(**_ids(event), original_start=original_start)


def deleted(event: Event) -> EventDeleted | None:
    """``None`` for an event that was never live."""
    if event.published_at is None:
        return None
    return EventDeleted(**_ids(event), was_published=is_live(event))
