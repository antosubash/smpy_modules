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
from sm_events.core.errors import Forbidden, NotFound
from sm_events.models import Calendar


@dataclass(frozen=True)
class CalendarRights:
    view: bool
    edit_calendar: bool
    own: bool
    write_events: bool
    see_drafts: bool
    publish: bool


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
    """The same policy queries as a list, for a single calendar."""
    rights = await calendar_rights_many(db, who, [calendar], include_deleted=include_deleted)
    return rights[calendar.id]


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
    """One ``SELECT`` per action for the whole page: shares live in the database,
    so ``POLICY.can`` on loaded calendars cannot see them."""
    ids = [c.id for c in calendars]
    if not ids:
        return {}
    view, edit, own, write = [
        await _allowed_ids(db, who, action, ids, trash=include_deleted)
        for action in (ACTION_VIEW, ACTION_EDIT, ACTION_DELETE, ACTION_WRITE_EVENTS)
    ]
    return {i: _rights(who, i in view, i in edit, i in own, i in write) for i in ids}


async def writable_calendar(db: Any, who: ResourcePrincipal, calendar_id: uuid.UUID) -> Calendar:
    """The calendar, when the caller may write events in it: ``NotFound`` for one
    that is missing or not visible, ``Forbidden`` for one they may only see."""
    calendar = (
        await db.execute(select(Calendar).where(Calendar.id == calendar_id))
    ).scalar_one_or_none()
    if calendar is None:
        raise NotFound
    rights = await calendar_rights(db, who, calendar)
    if not rights.view:
        raise NotFound
    if not rights.write_events:
        raise Forbidden(constants.EDIT_REFUSED_DETAIL)
    return calendar
