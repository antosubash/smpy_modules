"""Trash and restore. A soft delete that needs ``expected_revision``; the event
comes back with the status it had. There is no purge.

Both need the same right as a write: ``write_events`` on the calendar, plus
``events.publish`` when the event is published or scheduled. An event of a trashed
calendar is invisible because its calendar is.
"""

from __future__ import annotations

import uuid
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import select

from sm_events.content import bus, notices, revisions
from sm_events.content.fields import has_live_children
from sm_events.content.guard import claim
from sm_events.core.access.events import load_event, require
from sm_events.core.errors import HasSubEvents, InvalidParent
from sm_events.models import Event

__all__ = ["restore_event", "trash_event"]


async def trash_event(db: Any, who: ResourcePrincipal, event_id: uuid.UUID, expected: int) -> None:
    """Soft-delete. ``HasSubEvents`` while a live sub-event remains."""
    event, rights = await load_event(db, who, event_id)
    require(rights)
    async with db.begin_nested():
        await claim(db, event, expected, actor=who.user_id)
        if await has_live_children(db, event.id):
            raise HasSubEvents
        await db.delete(event)
        await db.flush()
        await revisions.record(db, event, action="trashed", actor=who.user_id)
        bus.emit(db, notices.deleted(event))


async def restore_event(
    db: Any, who: ResourcePrincipal, event_id: uuid.UUID, expected: int
) -> Event:
    """Bring a trashed event back. A sub-event whose parent is still trashed is
    ``InvalidParent``: restore the parent first."""
    event, rights = await load_event(db, who, event_id, trashed=True)
    require(rights)
    async with db.begin_nested():
        await claim(db, event, expected, actor=who.user_id, trashed=True)
        if event.parent_id is not None:
            parent = (await db.execute(select(Event.id).where(Event.id == event.parent_id))).first()
            if parent is None:
                raise InvalidParent
        event.is_deleted = False
        event.deleted_at = None
        event.deleted_by = None
        await db.flush()
        await revisions.record(db, event, action="restored", actor=who.user_id)
    return event
