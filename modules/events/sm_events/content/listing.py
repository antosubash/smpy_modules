"""``GET /events``: the console's event list, paged.

What is listed is what the caller may see (:func:`~sm_events.core.access.events.visible_events`):
drafts, in-review and scheduled events only on calendars they can write. A series
matches a date range when it intersects it (the master starts before ``to`` and
``recurrence_until`` is ``NULL`` or after ``from``), a one-off when
``starts_at < to AND ends_at > from``. ``trashed`` lists the trash instead, and
only what the caller could restore: events on calendars they may write, never one
of a trashed calendar. Ordered by ``starts_at`` then ``id``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import func
from sqlmodel import and_, col, or_, select

from sm_events.core import constants
from sm_events.core.access import ACTION_WRITE_EVENTS, POLICY
from sm_events.core.access.events import visible_events
from sm_events.models import Calendar, Event, EventText

__all__ = ["EventFilters", "list_events"]


@dataclass(frozen=True)
class EventFilters:
    calendar_ids: Sequence[uuid.UUID] = ()
    status: str | None = None
    category_id: uuid.UUID | None = None
    start: datetime | None = None
    end: datetime | None = None
    q: str | None = None
    trashed: bool = False


def _base(who: ResourcePrincipal, trashed: bool) -> Any:
    if not trashed:
        return visible_events(who)
    # ``include_deleted`` reaches the sub-select too, so a trashed calendar is
    # excluded explicitly: its events stay invisible.
    writable = POLICY.filter(
        who, ACTION_WRITE_EVENTS, select(Calendar.id).where(Calendar.is_deleted.is_(False))
    )
    return (
        select(Event)
        .where(Event.is_deleted.is_(True), col(Event.calendar_id).in_(writable))
        .execution_options(include_deleted=True)
    )


def _intersects(start: datetime | None, end: datetime | None) -> Any:
    one_off = [col(Event.rrule).is_(None)]
    series = [col(Event.rrule).is_not(None)]
    if end is not None:
        one_off.append(Event.starts_at < end)
        series.append(Event.starts_at < end)
    if start is not None:
        one_off.append(Event.ends_at > start)
        series.append(or_(col(Event.recurrence_until).is_(None), Event.recurrence_until > start))
    return or_(and_(*one_off), and_(*series))


def _filtered(who: ResourcePrincipal, f: EventFilters) -> Any:
    stmt = _base(who, f.trashed)
    if f.calendar_ids:
        stmt = stmt.where(col(Event.calendar_id).in_(list(f.calendar_ids)))
    if f.status == constants.STATUS_SCHEDULED:
        stmt = stmt.where(col(Event.publish_at).is_not(None))
    elif f.status is not None:
        stmt = stmt.where(Event.status == f.status)
    if f.category_id is not None:
        stmt = stmt.where(Event.category_id == f.category_id)
    if f.start is not None or f.end is not None:
        stmt = stmt.where(_intersects(f.start, f.end))
    if f.q:
        titled = select(EventText.event_id).where(
            col(EventText.title).icontains(f.q, autoescape=True)
        )
        stmt = stmt.where(col(Event.id).in_(titled))
    return stmt


async def list_events(
    db: Any, who: ResourcePrincipal, f: EventFilters, *, page: int, page_size: int
) -> tuple[list[Event], int]:
    """One page of events and the total that match."""
    stmt = _filtered(who, f)
    opts = stmt.get_execution_options()
    total = (
        await db.execute(
            select(func.count())
            .select_from(stmt.order_by(None).subquery())
            .execution_options(**opts)
        )
    ).scalar_one()
    rows = await db.execute(
        stmt.order_by(col(Event.starts_at), col(Event.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.scalars().all()), total
