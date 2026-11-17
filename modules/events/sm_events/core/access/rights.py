"""What one principal may do in one calendar, for the screens and the API."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from simple_module_core.resources import (
    ACTION_DELETE,
    ACTION_EDIT,
    ACTION_VIEW,
    ResourcePrincipal,
)
from sqlmodel import col, select

from sm_events.core import constants
from sm_events.core.access import ACTION_WRITE_EVENTS, POLICY
from sm_events.models import Calendar


@dataclass(frozen=True)
class CalendarRights:
    view: bool
    edit_calendar: bool
    own: bool
    write_events: bool
    see_drafts: bool
    publish: bool


async def _allowed(
    db: Any, who: ResourcePrincipal, action: str, calendar: Calendar, *, trash: bool
) -> bool:
    stmt = select(Calendar.id).where(Calendar.id == calendar.id)
    if trash:
        stmt = stmt.execution_options(include_deleted=True)
    return (await db.execute(POLICY.filter(who, action, stmt))).first() is not None


def _rights(
    who: ResourcePrincipal, view: bool, edit: bool, own: bool, write: bool
) -> CalendarRights:
    return CalendarRights(
        view=view,
        edit_calendar=edit,
        own=own,
        write_events=write,
        see_drafts=write,
        publish=write and who.has(constants.PERM_PUBLISH),
    )


async def calendar_rights(
    db: Any, who: ResourcePrincipal, calendar: Calendar, *, include_deleted: bool = False
) -> CalendarRights:
    """Asked of the database, one ``SELECT`` per action: a share is a row, and
    ``POLICY.can`` on a loaded object cannot see it."""
    view = await _allowed(db, who, ACTION_VIEW, calendar, trash=include_deleted)
    edit = await _allowed(db, who, ACTION_EDIT, calendar, trash=include_deleted)
    own = await _allowed(db, who, ACTION_DELETE, calendar, trash=include_deleted)
    write = await _allowed(db, who, ACTION_WRITE_EVENTS, calendar, trash=include_deleted)
    return _rights(who, view, edit, own, write)


async def _allowed_ids(
    db: Any, who: ResourcePrincipal, action: str, ids: list[uuid.UUID], *, trash: bool
) -> set[uuid.UUID]:
    stmt = select(Calendar.id).where(col(Calendar.id).in_(ids))
    if trash:
        stmt = stmt.execution_options(include_deleted=True)
    return set((await db.execute(POLICY.filter(who, action, stmt))).scalars().all())


async def calendar_rights_many(
    db: Any, who: ResourcePrincipal, calendars: Sequence[Calendar], *, include_deleted: bool = False
) -> dict[uuid.UUID, CalendarRights]:
    """:func:`calendar_rights` for a page of calendars: one ``SELECT`` per action,
    through the same policy filter, however many calendars there are."""
    ids = [c.id for c in calendars]
    if not ids:
        return {}
    view, edit, own, write = [
        await _allowed_ids(db, who, action, ids, trash=include_deleted)
        for action in (ACTION_VIEW, ACTION_EDIT, ACTION_DELETE, ACTION_WRITE_EVENTS)
    ]
    return {i: _rights(who, i in view, i in edit, i in own, i in write) for i in ids}
