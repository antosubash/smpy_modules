"""Who sees and who writes an event.

An event is visible when its calendar is visible **and** it is ``published`` or
the viewer may write events in that calendar. So a draft, an ``in_review`` event
and a scheduled one (``publish_at`` set, status unchanged) reach only writers; a
viewer, a share-view holder, someone without ``events.view`` and an anonymous
principal get published events only.

An event is **locked** when it is published or scheduled. A locked event can be
changed, trashed, restored or given overrides only by someone who may write it
**and** holds ``events.publish``; any other writer gets 403 ``publish_required``,
and someone who cannot see it gets 404.

No tenant predicate: events carry ``MultiTenantMixin`` and the tenancy guard
filters on the bound tenant.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from simple_module_core.resources import ACTION_VIEW, ResourcePrincipal
from sqlmodel import col, or_, select

from sm_events.core import constants
from sm_events.core.access import ACTION_WRITE_EVENTS, POLICY
from sm_events.core.access.rights import calendar_rights
from sm_events.core.errors import Forbidden, NotFound, PublishRequired
from sm_events.models import Calendar, Event
from sm_events.models.enums import EventStatus

__all__ = [
    "EventRights",
    "event_rights",
    "is_locked",
    "load_event",
    "require",
    "visible_events",
]


def visible_events(who: ResourcePrincipal, *, include_unpublished: bool = True) -> Any:
    """``SELECT Event`` narrowed to what *who* may see (trash excluded).

    ``include_unpublished=False`` hides everything unpublished, writers included
    (the public surface, and a caller who asked for published events only)."""
    in_visible_calendar = col(Event.calendar_id).in_(
        POLICY.filter(who, ACTION_VIEW, select(Calendar.id))
    )
    shown = Event.status == EventStatus.PUBLISHED.value
    if include_unpublished:
        writable = POLICY.filter(who, ACTION_WRITE_EVENTS, select(Calendar.id))
        shown = or_(shown, col(Event.calendar_id).in_(writable))
    return select(Event).where(in_visible_calendar, shown)


def is_locked(event: Event) -> bool:
    """Published, or scheduled to be: a change then needs ``events.publish``."""
    return event.status == EventStatus.PUBLISHED.value or event.publish_at is not None


@dataclass(frozen=True)
class EventRights:
    view: bool
    write: bool
    publish: bool
    locked: bool


async def event_rights(db: Any, who: ResourcePrincipal, event: Event) -> EventRights:
    """The calendar's rights narrowed to one event. A trashed calendar gives none."""
    locked = is_locked(event)
    calendar = (
        await db.execute(select(Calendar).where(Calendar.id == event.calendar_id))
    ).scalar_one_or_none()
    if calendar is None:
        return EventRights(view=False, write=False, publish=False, locked=locked)
    rights = await calendar_rights(db, who, calendar)
    published = event.status == EventStatus.PUBLISHED.value
    return EventRights(
        view=rights.view and (published or rights.write_events),
        write=rights.write_events,
        publish=rights.publish,
        locked=locked,
    )


def require(rights: EventRights, *, publish: bool = False) -> None:
    """Raise unless the caller may change the event (and, when ``publish``, publish)."""
    if not rights.view:
        raise NotFound
    if not rights.write:
        raise Forbidden(constants.EDIT_REFUSED_DETAIL)
    if (rights.locked or publish) and not rights.publish:
        raise PublishRequired


async def load_event(
    db: Any, who: ResourcePrincipal, event_id: uuid.UUID, *, trashed: bool = False
) -> tuple[Event, EventRights]:
    """The event and the caller's rights on it. ``NotFound`` for a missing event,
    another tenant's, or one the caller may not see (drafts included). A trashed
    event (``trashed=True``) is also ``NotFound`` to anyone without the write right on
    its calendar: a published one is visible to a viewer while alive, and answering
    them 403 on its trash would show that it exists."""
    stmt = select(Event).where(Event.id == event_id)
    if trashed:
        stmt = stmt.where(Event.is_deleted.is_(True)).execution_options(include_deleted=True)
    event = (await db.execute(stmt)).scalar_one_or_none()
    if event is None:
        raise NotFound
    rights = await event_rights(db, who, event)
    if not rights.view or (trashed and not rights.write):
        raise NotFound
    return event, rights
