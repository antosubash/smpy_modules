"""What one principal may do in one calendar, for the screens and the API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from simple_module_core.resources import (
    ACTION_DELETE,
    ACTION_EDIT,
    ACTION_VIEW,
    ResourcePrincipal,
)
from sqlmodel import select

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


async def calendar_rights(
    db: Any, who: ResourcePrincipal, calendar: Calendar, *, include_deleted: bool = False
) -> CalendarRights:
    """Asked of the database, one ``SELECT`` per action: a share is a row, and
    ``POLICY.can`` on a loaded object cannot see it."""
    view = await _allowed(db, who, ACTION_VIEW, calendar, trash=include_deleted)
    edit = await _allowed(db, who, ACTION_EDIT, calendar, trash=include_deleted)
    own = await _allowed(db, who, ACTION_DELETE, calendar, trash=include_deleted)
    write = await _allowed(db, who, ACTION_WRITE_EVENTS, calendar, trash=include_deleted)
    return CalendarRights(
        view=view,
        edit_calendar=edit,
        own=own,
        write_events=write,
        see_drafts=write,
        publish=write and who.has(constants.PERM_PUBLISH),
    )
