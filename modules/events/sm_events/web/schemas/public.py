"""Query parsing for the anonymous surface.

One answer for bad input: a malformed value is a 422 (FastAPI's own list shape for a type error, the
``{"detail", "code"}`` envelope for a range the read refuses), never a guess. Nothing here reveals
whether an id exists: a calendar or category id the public may not see matches nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Literal

from fastapi import Depends, Query
from pydantic import BaseModel, Field

from sm_events.core import constants, locales
from sm_events.web.schemas._fields import SupportedInstant

__all__ = [
    "AlternateOut",
    "BlockCalendarOut",
    "BlockCalendarsOut",
    "BlockQuery",
    "CategoryRef",
    "MonthGroup",
    "PublicCalendarOut",
    "PublicCalendarRef",
    "PublicCategoryOut",
    "PublicIndexProps",
    "PublicListItem",
    "PublicOccurrenceParams",
    "PublicOccurrenceQuery",
    "UpcomingOut",
    "block_query",
    "public_occurrence_query",
]


@dataclass(frozen=True)
class PublicOccurrenceQuery:
    start: SupportedInstant
    end: SupportedInstant
    calendar_ids: frozenset[uuid.UUID] | None
    category_ids: frozenset[uuid.UUID] | None
    locale: str


def public_occurrence_query(
    start: Annotated[SupportedInstant, Query()],
    end: Annotated[SupportedInstant, Query()],
    calendar: Annotated[list[uuid.UUID] | None, Query(max_length=constants.CALENDARS_MAX)] = None,
    category: Annotated[list[uuid.UUID] | None, Query(max_length=constants.CATEGORIES_MAX)] = None,
    locale: Annotated[str | None, Query(max_length=constants.LOCALE_MAX)] = None,
    type: Annotated[list[str] | None, Query(max_length=20)] = None,
) -> PublicOccurrenceQuery:
    """The query string as one value. ``type`` is accepted and ignored (the grid's filter bar
    sends it); an unknown ``locale`` is the default language."""
    return PublicOccurrenceQuery(
        start=start,
        end=end,
        calendar_ids=frozenset(calendar) if calendar else None,
        category_ids=frozenset(category) if category else None,
        locale=locale if locale in locales.supported() else locales.default(),  # type: ignore[arg-type]
    )


PublicOccurrenceParams = Annotated[PublicOccurrenceQuery, Depends(public_occurrence_query)]


# --- what the index, a calendar's page and the 404's suggestions render --------------------
# Response models: no input bounds, so an old row can always be shown. Every URL is a path (the
# origin is the page's, never baked into props), so props do not depend on the ``Host`` header.


class PublicCalendarRef(BaseModel):
    slug: str
    name: str
    color: str


class CategoryRef(BaseModel):
    slug: str
    name: str
    color: str | None


class PublicListItem(BaseModel):
    """One occurrence in a list, in the event's own clock. ``end_date`` is the last day
    (inclusive); ``lang`` is the language of ``title`` and of the page ``url`` points at."""

    key: str
    url: str
    title: str
    lang: str
    all_day: bool
    start_local: str
    end_local: str
    start_date: date | None
    end_date: date | None
    timezone: str
    show_timezone: bool
    status: Literal["confirmed", "cancelled"]
    rescheduled: bool
    calendar: PublicCalendarRef
    category: CategoryRef | None
    venue_name: str | None
    attendance_mode: str
    summary: str | None
    image: str | None = None
    """An absolute http(s) address as stored, else ``None``."""


class MonthGroup(BaseModel):
    month: str
    items: list[PublicListItem]


class PublicCalendarOut(BaseModel):
    id: str
    slug: str
    name: str
    color: str
    description: str | None
    default_timezone: str
    url: str
    feed_url: str


class PublicCategoryOut(BaseModel):
    id: str
    slug: str
    name: str
    color: str | None


class AlternateOut(BaseModel):
    locale: str
    url: str


class PublicIndexProps(BaseModel):
    locale: str
    title: str
    page: int
    page_count: int
    groups: list[MonthGroup]
    calendars: list[PublicCalendarOut]
    calendar: PublicCalendarOut | None
    categories: list[PublicCategoryOut]
    category: str | None
    view: Literal["list", "calendar"]
    feed_url: str
    default_timezone: str
    api_url: str
    alternates: list[AlternateOut]


# --- the pagebuilder blocks' routes (``/api/events/public/*``) ------------------------------


@dataclass(frozen=True)
class BlockQuery:
    """What a block asks for. Calendars and the category are slugs, resolved on every request;
    ``locale`` is the page's language (an unknown one is the default)."""

    calendars: tuple[str, ...]
    category: str | None
    count: int
    locale: str


Slugs = Annotated[
    list[Annotated[str, Field(max_length=constants.SLUG_MAX)]] | None,
    Query(max_length=constants.BLOCK_CALENDARS_MAX),
]


def block_query(
    calendar: Slugs = None,
    category: Annotated[str | None, Query(max_length=constants.SLUG_MAX)] = None,
    count: Annotated[
        int, Query(ge=1, le=constants.UPCOMING_BLOCK_MAX)
    ] = constants.UPCOMING_BLOCK_DEFAULT,
    locale: Annotated[str | None, Query(max_length=constants.LOCALE_MAX)] = None,
) -> BlockQuery:
    return BlockQuery(
        calendars=tuple(dict.fromkeys(calendar or ())),
        category=category or None,
        count=count,
        locale=locale if locale in locales.supported() else locales.default(),  # type: ignore[arg-type]
    )


class BlockCalendarOut(BaseModel):
    id: str
    slug: str
    name: str
    color: str
    default_timezone: str


class BlockCalendarsOut(BaseModel):
    calendars: list[BlockCalendarOut]
    categories: list[PublicCategoryOut]
    default_timezone: str


class UpcomingOut(BaseModel):
    items: list[PublicListItem]
