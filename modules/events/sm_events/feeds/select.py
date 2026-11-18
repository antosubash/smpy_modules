"""The feed read: public events with their rules, overrides, texts and parents.

Everything starts from :func:`~sm_events.core.access.public.public_events`, so a draft, an
event of an internal or private calendar, a trashed row or another tenant's never reaches a
feed. It reads rows, not occurrences: a series is handed over as its master with **all** its
overrides (an ``EXDATE`` outside the window still hides an instance a client expands).

**Window and caps (Ruling 25).** A calendar feed holds the masters that meet
``[now - FEED_DAYS_BACK, now + FEED_DAYS_AHEAD)`` (a one-off by its span, a series by its first
start and ``recurrence_until``), by start, at most ``FEED_MAX_EVENTS`` of them and
``FEED_MAX_COMPONENTS`` ``VEVENT`` components. When a series would cross the component cap, it
and every later master are dropped, never a series without its ``EXDATE``s. ``truncated``
says anything was cut.

Four statements however many events: the events, the overrides of the series, the categories
and the public parents (the texts are a fifth, in the shared helper).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlmodel import col

from sm_events.content.public_read import pick_text
from sm_events.content.texts import texts_of
from sm_events.core import constants
from sm_events.core.access.public import public_events
from sm_events.core.tenancy import bound_tenant
from sm_events.feeds.ics_event import FeedEvent
from sm_events.models import Category, Event, OccurrenceOverride, OverrideKind

__all__ = ["FeedRead", "feed_events", "single_event"]

UrlFor = Callable[[str, str], str]
_SHOWN = (OverrideKind.MOVED.value, OverrideKind.CANCELLED.value)


@dataclass(frozen=True)
class FeedRead:
    items: list[FeedEvent]
    truncated: bool


def _in_window(lo: datetime, hi: datetime) -> Any:
    one_off = and_(col(Event.rrule).is_(None), Event.ends_at > lo, Event.starts_at < hi)
    series = and_(
        col(Event.rrule).is_not(None),
        Event.starts_at < hi,
        or_(col(Event.recurrence_until).is_(None), Event.recurrence_until > lo),
    )
    return or_(one_off, series)


async def _overrides(db: Any, events: Sequence[Event]) -> dict[uuid.UUID, list[OccurrenceOverride]]:
    ids = [e.id for e in events if e.rrule]
    found: dict[uuid.UUID, list[OccurrenceOverride]] = {i: [] for i in ids}
    if ids:
        stmt = (
            select(OccurrenceOverride)
            .where(
                OccurrenceOverride.tenant_id == bound_tenant(),  # type: ignore[arg-type]
                col(OccurrenceOverride.event_id).in_(ids),
            )
            .order_by(col(OccurrenceOverride.original_start))
        )
        for row in (await db.execute(stmt)).scalars():
            found[row.event_id].append(row)
    return found


async def _categories(db: Any, events: Sequence[Event]) -> dict[uuid.UUID, Category]:
    ids = {e.category_id for e in events if e.category_id}
    if not ids:
        return {}
    stmt = select(Category).where(
        Category.tenant_id == bound_tenant(),  # type: ignore[arg-type]
        col(Category.id).in_(ids),
    )
    return {c.id: c for c in (await db.execute(stmt)).scalars()}


async def _parent_uids(db: Any, events: Iterable[Event]) -> dict[uuid.UUID, str]:
    """The UID of each parent that is itself public; a hidden parent is simply absent."""
    ids = {e.parent_id for e in events if e.parent_id}
    if not ids:
        return {}
    stmt = public_events().with_only_columns(Event.id, Event.uid).where(col(Event.id).in_(ids))
    return {row[0]: row[1] for row in (await db.execute(stmt)).all()}


def _category_name(cat: Category | None, locale: str, default: str) -> str | None:
    if cat is None or not cat.names:
        return None
    return cat.names.get(locale) or cat.names.get(default) or cat.names[min(cat.names)]


async def _items(
    db: Any, events: Sequence[Event], *, locale: str, default_locale: str, url_for: UrlFor
) -> list[FeedEvent]:
    texts = await texts_of(db, [e.id for e in events])
    overrides = await _overrides(db, events)
    categories = await _categories(db, events)
    parents = await _parent_uids(db, events)
    items: list[FeedEvent] = []
    for event in events:
        if not texts[event.id]:  # an event always has its default text; skip a broken one
            continue
        text = pick_text(texts[event.id], locale, default_locale)
        items.append(
            FeedEvent(
                event=event,
                text=text,
                overrides=tuple(overrides.get(event.id, ())),
                url=url_for(text.slug, text.locale),
                category=_category_name(categories.get(event.category_id), locale, default_locale),  # type: ignore[arg-type]
                parent_uid=parents.get(event.parent_id) if event.parent_id else None,
            )
        )
    return items


def _components(item: FeedEvent) -> int:
    """The master, plus a ``VEVENT`` per moved or cancelled occurrence (a skip is an EXDATE)."""
    if not item.event.rrule:
        return 1
    return 1 + sum(1 for o in item.overrides if o.kind in _SHOWN)


async def feed_events(
    db: Any,
    *,
    calendar_id: uuid.UUID | None,
    locale: str,
    default_locale: str,
    now: datetime,
    url_for: UrlFor,
) -> FeedRead:
    """The public feed's items for ``calendar_id`` (every public calendar when ``None``)."""
    lo = now - timedelta(days=constants.FEED_DAYS_BACK)
    hi = now + timedelta(days=constants.FEED_DAYS_AHEAD)
    stmt = public_events().where(_in_window(lo, hi))
    if calendar_id is not None:
        stmt = stmt.where(Event.calendar_id == calendar_id)
    stmt = stmt.order_by(col(Event.starts_at), col(Event.id)).limit(constants.FEED_MAX_EVENTS + 1)
    events = list((await db.execute(stmt)).scalars().all())
    truncated = len(events) > constants.FEED_MAX_EVENTS
    items = await _items(
        db,
        events[: constants.FEED_MAX_EVENTS],
        locale=locale,
        default_locale=default_locale,
        url_for=url_for,
    )
    kept: list[FeedEvent] = []
    used = 0
    for item in items:
        used += _components(item)
        if used > constants.FEED_MAX_COMPONENTS:
            truncated = True
            break
        kept.append(item)
    return FeedRead(items=kept, truncated=truncated)


async def single_event(
    db: Any, event: Event, *, locale: str, default_locale: str, url_for: UrlFor
) -> FeedEvent:
    """One event, whole: no window, every override. The caller has already passed it through
    the gate (``event_by_slug``)."""
    (item,) = await _items(
        db, [event], locale=locale, default_locale=default_locale, url_for=url_for
    )
    return item
