"""The upcoming list: one read, enriched, grouped by month and cut into pages (Ruling 14).

The list covers ``[now, now + MAX_RANGE_DAYS)`` of the public occurrences read (so at most 2,000
items, and no past events), in the read's own order, ``PAGE_SIZE`` to a page, grouped by the
month of the event's local start. Times are the event's own clock, with its timezone named
when it differs from its calendar's. An event without a text in the visitor's language shows
its default-language text (or its first), marked ``lang``, and links to the page in *that*
language.

Everything comes from the gate: the read is the anonymous one, the event, calendar and category
rows are fetched through ``public_events()``, ``public_calendars()`` and ``public_categories()``,
and an occurrence whose event is not found there is dropped.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlmodel import col

from sm_events.calendar.times import Span, all_day_dates, to_local
from sm_events.content.public_read import (
    pick_text,
    public_categories,
    public_texts,
)
from sm_events.core import constants
from sm_events.core.access.public import public_calendars, public_events
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Calendar, Category, Event, EventText
from sm_events.web.endpoints.public import _urls
from sm_events.web.endpoints.public._api import occurrence_day, public_read
from sm_events.web.schemas.public import (
    CategoryRef,
    MonthGroup,
    PublicCalendarRef,
    PublicListItem,
)

__all__ = ["category_name", "make_item", "month_groups", "page_count", "page_param", "upcoming"]


def page_param(raw: str | None) -> int:
    """``?page=`` read leniently: anything that is not a positive whole number is page 1. A number
    past the last page is the caller's 404."""
    if raw is not None and raw.isascii() and raw.isdigit() and int(raw) >= 1:
        return int(raw)
    return 1


def page_count(total: int) -> int:
    return max(1, -(-total // constants.PAGE_SIZE))


def category_name(category: Category, locale: str, default: str) -> str:
    names = category.names or {}
    return (
        names.get(locale) or names.get(default) or (names[min(names)] if names else category.slug)
    )


async def _events(db: Any, ids: set[uuid.UUID]) -> dict[uuid.UUID, Event]:
    if not ids:
        return {}
    stmt = public_events().where(col(Event.id).in_(ids))
    return {e.id: e for e in (await db.execute(stmt)).scalars()}


async def _calendars(db: Any) -> dict[uuid.UUID, Calendar]:
    stmt = public_calendars().limit(constants.CALENDARS_MAX)
    return {c.id: c for c in (await db.execute(stmt)).scalars()}


def make_item(
    *,
    key: str,
    event: Event,
    text: EventText,
    calendar: Calendar,
    category: Category | None,
    locale: str,
    default_locale: str,
    span: Span,
    day: date | None,
    status: str,
    rescheduled: bool,
) -> PublicListItem:
    """One list item for an event (or one of its occurrences) shown in ``span``; ``text`` is the
    already-chosen language and ``day`` the ``?date=`` of a series instance."""
    start_local, end_local = to_local(span, all_day=event.all_day, timezone=event.timezone)
    first = last = None
    if event.all_day:
        first, after = all_day_dates(span, event.timezone)
        last = after - timedelta(days=1)
    return PublicListItem(
        key=key,
        url=_urls.event_path(text.slug, text.locale, day),
        title=text.title,
        lang=text.locale,
        all_day=event.all_day,
        start_local=start_local,
        end_local=end_local,
        start_date=first,
        end_date=last,
        timezone=event.timezone,
        show_timezone=event.timezone != calendar.default_timezone,
        status="cancelled" if status == "cancelled" or event.cancelled else "confirmed",
        rescheduled=rescheduled,
        calendar=PublicCalendarRef(slug=calendar.slug, name=calendar.name, color=calendar.color),
        category=None
        if category is None
        else CategoryRef(
            slug=category.slug,
            name=category_name(category, locale, default_locale),
            color=category.color,
        ),
        venue_name=event.venue_name,
        attendance_mode=event.attendance_mode,
        summary=text.summary,
    )


async def upcoming(
    db: Any,
    *,
    locale: str,
    default_locale: str,
    now: datetime,
    calendar_id: uuid.UUID | None,
    category_id: uuid.UUID | None,
) -> list[PublicListItem]:
    """Every upcoming public occurrence in the window, as list items."""
    page = await public_read(
        db,
        tenant=bound_tenant(),
        start=now,
        end=now + timedelta(days=constants.MAX_RANGE_DAYS),
        calendar_ids=frozenset({calendar_id}) if calendar_id else None,
        category_ids=frozenset({category_id}) if category_id else None,
        locale=locale,
    )
    ids = {i.event_id for i in page.items if i.event_id}
    events = await _events(db, ids)
    texts = await public_texts(db, ids)
    cals = await _calendars(db)
    cats = {c.id: c for c in await public_categories(db)}
    items: list[PublicListItem] = []
    for occ in page.items:
        event = events.get(occ.event_id) if occ.event_id else None
        calendar = cals.get(occ.calendar_id)
        if event is None or calendar is None or not texts.get(event.id):
            continue
        items.append(
            make_item(
                key=occ.key,
                event=event,
                text=pick_text(texts[event.id], locale, default_locale),
                calendar=calendar,
                category=cats.get(event.category_id) if event.category_id else None,
                locale=locale,
                default_locale=default_locale,
                span=Span(occ.start, occ.end),
                day=occurrence_day(occ),
                status=occ.status,
                rescheduled=occ.original_start is not None and occ.original_start != occ.start,
            )
        )
    return items


def _month(item: PublicListItem) -> str:
    return item.start_local[:7]


def month_groups(items: list[PublicListItem], page: int) -> list[MonthGroup]:
    """The ``page``-th slice of ``items``, grouped by local month in order."""
    start = (page - 1) * constants.PAGE_SIZE
    grouped: dict[str, list[PublicListItem]] = defaultdict(list)
    for item in items[start : start + constants.PAGE_SIZE]:
        grouped[_month(item)].append(item)
    return [MonthGroup(month=m, items=grouped[m]) for m in sorted(grouped)]
