"""The SQL behind the occurrences read: three bounded statements and one for texts.

Every statement starts from :func:`~sm_events.core.access.events.visible_events`,
so a draft never reaches a viewer who cannot write the calendar. The fixed
look-back (:data:`~sm_events.core.constants.MAX_SERIES_EVENT_DAYS` plus a margin for
a DST hour) is the longest an instance can be, so an instance meeting the window
cannot have started earlier.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlmodel import and_, col, or_, select

from sm_events.calendar.occurrence import OccurrenceFilters
from sm_events.core import constants
from sm_events.core.access import ACTION_WRITE_EVENTS, POLICY
from sm_events.core.access.events import visible_events
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Calendar, Category, Event, EventText, OccurrenceOverride, OverrideKind

__all__ = ["Row", "one_offs", "overrides", "series", "texts", "writable_calendars"]

LOOK_BACK = timedelta(days=constants.MAX_SERIES_EVENT_DAYS + constants.LOOK_BACK_MARGIN_DAYS)

Row = tuple[Event, str, str | None]
"""An event with its calendar's colour and its category's (if any)."""


def _base(viewer: ResourcePrincipal, filters: OccurrenceFilters) -> Any:
    stmt = (
        visible_events(viewer, include_unpublished=filters.include_unpublished)
        .join(Calendar, col(Calendar.id) == col(Event.calendar_id))
        .outerjoin(Category, col(Category.id) == col(Event.category_id))
        .add_columns(col(Calendar.color), col(Category.color))
        # Explicit, beside the framework's filter: the contract reads through here.
        .where(col(Event.tenant_id) == bound_tenant())
    )
    if filters.calendar_ids is not None:
        stmt = stmt.where(col(Event.calendar_id).in_(filters.calendar_ids))
    if filters.category_ids is not None:
        stmt = stmt.where(col(Event.category_id).in_(filters.category_ids))
    if filters.types is not None:
        stmt = stmt.where(col(Event.type).in_(filters.types))
    if filters.event_ids is not None:
        stmt = stmt.where(col(Event.id).in_(filters.event_ids))
    return stmt


async def one_offs(
    db: Any, viewer: ResourcePrincipal, start: datetime, end: datetime, filters: OccurrenceFilters
) -> list[Row]:
    """Non-recurring events meeting the window, at most ``MAX_OCCURRENCES + 1``."""
    stmt = (
        _base(viewer, filters)
        .where(col(Event.rrule).is_(None), Event.starts_at < end, Event.ends_at > start)
        .order_by(col(Event.starts_at), col(Event.ends_at), col(Event.id))
        .limit(constants.MAX_OCCURRENCES + 1)
    )
    return [tuple(r) for r in (await db.execute(stmt)).all()]  # type: ignore[misc]


def _moved_into_window(tenant_id: str, start: datetime, end: datetime) -> Any:
    """Series with an occurrence moved into the window from anywhere in time. The
    tenant predicate is explicit: this mapper sits in a sub-select."""
    return (
        select(OccurrenceOverride.event_id)
        .where(
            OccurrenceOverride.tenant_id == tenant_id,
            OccurrenceOverride.kind == OverrideKind.MOVED.value,
            col(OccurrenceOverride.starts_at) < end,
            col(OccurrenceOverride.ends_at) > start,
        )
        .scalar_subquery()
    )


async def series(
    db: Any,
    viewer: ResourcePrincipal,
    tenant_id: str,
    start: datetime,
    end: datetime,
    filters: OccurrenceFilters,
) -> tuple[list[Row], bool]:
    """Recurring events that may have an instance in the window (or one moved into
    it), at most ``SERIES_FETCH_MAX``; the flag says there were more."""
    prefilter = and_(
        Event.starts_at < end,
        or_(col(Event.recurrence_until).is_(None), Event.recurrence_until > start),
    )
    stmt = (
        _base(viewer, filters)
        .where(
            col(Event.rrule).is_not(None),
            or_(prefilter, col(Event.id).in_(_moved_into_window(tenant_id, start, end))),
        )
        .order_by(col(Event.starts_at), col(Event.id))
        .limit(constants.SERIES_FETCH_MAX + 1)
    )
    rows = [tuple(r) for r in (await db.execute(stmt)).all()]
    return rows[: constants.SERIES_FETCH_MAX], len(rows) > constants.SERIES_FETCH_MAX  # type: ignore[return-value]


async def overrides(
    db: Any, event_ids: list[uuid.UUID], start: datetime, end: datetime
) -> dict[uuid.UUID, dict[datetime, OccurrenceOverride]]:
    """``{event: {original_start: override}}`` for instances that can meet the
    window or that were moved into it."""
    if not event_ids:
        return {}
    stmt = select(OccurrenceOverride).where(
        col(OccurrenceOverride.event_id).in_(event_ids),
        or_(
            and_(
                OccurrenceOverride.original_start >= start - LOOK_BACK,
                OccurrenceOverride.original_start < end,
            ),
            and_(
                col(OccurrenceOverride.starts_at) < end,
                col(OccurrenceOverride.ends_at) > start,
            ),
        ),
    )
    found: dict[uuid.UUID, dict[datetime, OccurrenceOverride]] = defaultdict(dict)
    for row in (await db.execute(stmt)).scalars():
        found[row.event_id][row.original_start] = row
    return found


async def texts(db: Any, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, str]]:
    """``{event: {locale: title}}`` in one query."""
    if not event_ids:
        return {}
    stmt = select(EventText.event_id, EventText.locale, EventText.title).where(
        col(EventText.event_id).in_(event_ids)
    )
    found: dict[uuid.UUID, dict[str, str]] = defaultdict(dict)
    for event_id, locale, title in (await db.execute(stmt)).all():
        found[event_id][locale] = title
    return found


async def writable_calendars(db: Any, viewer: ResourcePrincipal) -> set[uuid.UUID]:
    """The calendars the viewer may write events in (for ``editable``)."""
    stmt = POLICY.filter(viewer, ACTION_WRITE_EVENTS, select(Calendar.id))
    return set((await db.execute(stmt)).scalars().all())
