"""Checks on an event's fields that need the database: its category and parent."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from sm_events.core.errors import InvalidParent, UnknownCategory
from sm_events.models import Category, Event

__all__ = ["check_category", "check_parent", "has_live_children"]


async def check_category(db: Any, category_id: uuid.UUID | None) -> None:
    """``UnknownCategory`` unless the category exists in the bound tenant."""
    if category_id is None:
        return
    found = (await db.execute(select(Category.id).where(Category.id == category_id))).first()
    if found is None:
        raise UnknownCategory


async def has_live_children(db: Any, event_id: uuid.UUID) -> bool:
    """Does the event have sub-events that are not in the trash?"""
    count = (
        await db.execute(select(func.count()).select_from(Event).where(Event.parent_id == event_id))
    ).scalar_one()
    return bool(count)


async def check_parent(db: Any, calendar_id: uuid.UUID, parent_id: uuid.UUID) -> Event:
    """The parent of a new sub-event: live, in the same calendar, one level only
    (it has no parent itself) and not recurring. ``InvalidParent`` otherwise,
    whatever the reason, so a parent in a calendar the caller cannot see is not
    told apart from one that does not exist."""
    parent = (await db.execute(select(Event).where(Event.id == parent_id))).scalar_one_or_none()
    if (
        parent is None
        or parent.calendar_id != calendar_id
        or parent.parent_id is not None
        or parent.rrule is not None
    ):
        raise InvalidParent
    return parent
