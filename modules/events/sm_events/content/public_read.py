"""Lookups for the public pages, every one on top of the gate.

Each function composes :func:`~sm_events.core.access.public.public_events` or
:func:`~sm_events.core.access.public.public_calendars` with its own ``WHERE``; none builds
a predicate on ``status``, ``visibility`` or trash itself, so a draft, an event of an
internal or private calendar, a trashed row or another tenant's row can never be found
here, by slug, by an old slug, by parent or by category.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlmodel import col

from sm_events.content.texts import texts_of
from sm_events.core import constants
from sm_events.core.access.public import public_calendars, public_events
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Calendar, Category, Event, EventText, Redirect

_SLUG = re.compile(constants.SLUG_PATTERN)

__all__ = [
    "calendar_by_slug",
    "category_by_slug",
    "event_by_slug",
    "pick_text",
    "public_categories",
    "public_children",
    "public_parent",
    "public_texts",
    "resolve_event_redirect",
    "valid_slug",
]


def valid_slug(value: str, max_len: int = constants.SLUG_MAX) -> bool:
    """Could ``value`` be a stored slug? One that cannot (a NUL byte, a space, too long) is
    answered as a miss without asking the database, which would refuse some of them."""
    return len(value) <= max_len and _SLUG.fullmatch(value) is not None


async def event_by_slug(db: Any, locale: str, slug: str) -> tuple[Event, EventText] | None:
    """The public event whose text in ``locale`` has ``slug``, with that text."""
    if not valid_slug(slug, constants.TEXT_SLUG_MAX):
        return None
    stmt = (
        public_events()
        .join(EventText, col(EventText.event_id) == col(Event.id))
        .where(
            EventText.tenant_id == bound_tenant(),  # type: ignore[arg-type]
            EventText.locale == locale,
            EventText.slug == slug,
        )
        .add_columns(EventText)
    )
    row = (await db.execute(stmt)).first()
    return None if row is None else (row[0], row[1])


async def resolve_event_redirect(db: Any, locale: str, slug: str) -> str | None:
    """The current slug in ``locale`` of the event an old ``slug`` pointed at, only when
    that event is public and has a text there. Anything else is ``None``: a 301 to a
    draft's current slug would publish the slug."""
    if not valid_slug(slug, constants.TEXT_SLUG_MAX):
        return None
    redirect = Redirect.__table__  # type: ignore[attr-defined]
    stmt = (
        select(EventText.slug)
        .join(redirect, redirect.c.event_id == EventText.event_id)
        .where(
            redirect.c.tenant_id == bound_tenant(),
            redirect.c.locale == locale,
            redirect.c.old_slug == slug,
            EventText.tenant_id == bound_tenant(),  # type: ignore[arg-type]
            EventText.locale == locale,
            col(EventText.event_id).in_(public_events().with_only_columns(Event.id)),
        )
    )
    current = (await db.execute(stmt)).scalar_one_or_none()
    return None if current in (None, slug) else current


async def calendar_by_slug(db: Any, slug: str) -> Calendar | None:
    if not valid_slug(slug):
        return None
    return (await db.execute(public_calendars().where(Calendar.slug == slug))).scalars().first()


async def public_children(db: Any, parent_id: uuid.UUID) -> list[Event]:
    """The publicly visible sub-events of a publicly visible parent, by start. A parent
    that is not public has none to list."""
    visible_parent = public_events().with_only_columns(Event.id).where(Event.id == parent_id)
    stmt = (
        public_events()
        .where(col(Event.parent_id) == parent_id, col(Event.parent_id).in_(visible_parent))
        .order_by(col(Event.starts_at), col(Event.id))
        .limit(constants.SUB_EVENTS_MAX)
    )
    return list((await db.execute(stmt)).scalars().all())


async def public_parent(db: Any, event: Event) -> Event | None:
    """The parent of ``event``, unless it is not public."""
    if event.parent_id is None:
        return None
    stmt = public_events().where(Event.id == event.parent_id)
    return (await db.execute(stmt)).scalars().first()


async def public_texts(
    db: Any, event_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, dict[str, EventText]]:
    """``{event id: {locale: text}}`` for those of ``event_ids`` that are public; the
    others are simply absent."""
    wanted = list(dict.fromkeys(event_ids))
    if not wanted:
        return {}
    stmt = public_events().with_only_columns(Event.id).where(col(Event.id).in_(wanted))
    visible = list((await db.execute(stmt)).scalars().all())
    return await texts_of(db, visible)


async def public_categories(db: Any) -> list[Category]:
    """The categories at least one public event uses, by slug."""
    used = (
        public_events()
        .with_only_columns(Event.category_id)
        .where(col(Event.category_id).is_not(None))
    )
    stmt = (
        select(Category)
        .where(Category.tenant_id == bound_tenant(), col(Category.id).in_(used))  # type: ignore[arg-type]
        .order_by(col(Category.slug))
    )
    return list((await db.execute(stmt)).scalars().all())


async def category_by_slug(db: Any, slug: str) -> Category | None:
    if not valid_slug(slug):
        return None
    return next((c for c in await public_categories(db) if c.slug == slug), None)


def pick_text(texts: Mapping[str, EventText], locale: str, default: str) -> EventText:
    """The text to show a visitor reading in ``locale``: that one, else the default
    language's, else the first by locale tag. ``texts`` is never empty for a real event
    (the default language is required); an empty one is a caller's bug."""
    for wanted in (locale, default):
        if wanted in texts:
            return texts[wanted]
    return texts[min(texts)]
