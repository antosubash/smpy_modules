"""What an event page reads, in one place, through the gate.

The event came from ``event_by_slug``; its calendar from ``public_calendars()``, its sub-events and
parent from ``public_children`` and ``public_parent``, its category from ``public_categories()``.
A child of a hidden parent has no parent here (so none anywhere), and a parent holds only its
publicly visible children. The validator parts are what the page's weak ``ETag`` covers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlmodel import col

from sm_events.content.public_read import (
    pick_text,
    public_categories,
    public_children,
    public_parent,
    public_texts,
)
from sm_events.content.texts import texts_of
from sm_events.core import locales
from sm_events.core.access.public import public_calendars
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Calendar, Category, Event, EventText, OccurrenceOverride
from sm_events.web.endpoints.public._occurrence import ShownOccurrence

__all__ = ["EventContext", "load_context", "validator_parts"]


@dataclass
class EventContext:
    event: Event
    text: EventText
    texts: dict[str, EventText]
    calendar: Calendar
    category: Category | None
    parent: Event | None
    parent_text: EventText | None
    children: list[Event]
    child_texts: dict[Any, dict[str, EventText]]
    overrides: list[OccurrenceOverride]
    locale: str


async def load_context(db: Any, event: Event, text: EventText, locale: str) -> EventContext | None:
    """Everything the page reads, or ``None`` if the calendar is not public (cannot happen for an
    event the gate returned, but the page never assumes it)."""
    calendar = (
        (await db.execute(public_calendars().where(Calendar.id == event.calendar_id)))
        .scalars()
        .first()
    )
    if calendar is None:
        return None
    texts = (await texts_of(db, [event.id]))[event.id]
    category = next((c for c in await public_categories(db) if c.id == event.category_id), None)
    parent = await public_parent(db, event)
    parent_text = None
    if parent is not None:
        parent_texts = (await public_texts(db, [parent.id])).get(parent.id)
        parent_text = pick_text(parent_texts, locale, locales.default()) if parent_texts else None
        parent = parent if parent_text is not None else None
    children = await public_children(db, event.id)
    child_texts = await public_texts(db, [c.id for c in children])
    overrides: list[OccurrenceOverride] = []
    if event.rrule:
        stmt = select(OccurrenceOverride).where(
            OccurrenceOverride.tenant_id == bound_tenant(),  # type: ignore[arg-type]
            col(OccurrenceOverride.event_id) == event.id,
        )
        overrides = list((await db.execute(stmt)).scalars())
    return EventContext(
        event, text, texts, calendar, category, parent, parent_text, children, child_texts,
        overrides, locale,
    )  # fmt: skip


def validator_parts(
    ctx: EventContext, shown: ShownOccurrence | None, upcoming: list[ShownOccurrence]
) -> list[object]:
    """What the page's weak ``ETag`` covers (Ruling 22, plus the category and parent it also
    shows): identities and revisions, never content."""
    event = ctx.event
    return [
        event.id,
        event.revision,
        ctx.text.id,
        ctx.calendar.id,
        ctx.calendar.updated_at,
        ctx.category.id if ctx.category else None,
        ctx.category.updated_at if ctx.category else None,
        ctx.parent.id if ctx.parent else None,
        ctx.parent.revision if ctx.parent else None,
        *[(c.id, c.revision) for c in ctx.children],
        ctx.locale,
        shown.date_param if shown else None,
        *[u.date_param for u in upcoming[:1]],  # a series page moves on as time passes
    ]
