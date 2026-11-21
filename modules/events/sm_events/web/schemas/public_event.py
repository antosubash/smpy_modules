"""What the event page renders. Response models: no input bounds, and every URL a path (the origin
belongs to the page's head, never to props), except the canonical and ``hreflang`` ones, which are
absolute because a crawler needs them so."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from sm_events.content.richtext_tree import Node
from sm_events.web.schemas.public import (
    AlternateOut,
    CategoryRef,
    PublicCalendarRef,
    PublicListItem,
)

__all__ = [
    "CalendarLink",
    "NextOccurrence",
    "ParentLink",
    "PlaceOut",
    "PublicEventProps",
    "SeriesOut",
    "WhenOut",
]

Status = Literal["scheduled", "cancelled", "rescheduled"]


class WhenOut(BaseModel):
    """The one occurrence a page is about, in the event's own clock plus the UTC instants."""

    start: datetime
    end: datetime
    all_day: bool
    start_local: str
    end_local: str
    start_date: date | None
    end_date: date | None
    status: Status
    previous_start_local: str | None
    date_param: date | None


class NextOccurrence(BaseModel):
    date_param: date | None
    url: str
    start_local: str
    end_local: str
    status: Status


class SeriesOut(BaseModel):
    """A recurring event: the normalised rule and the first start, so the client can summarise
    it, and the next occurrences."""

    rule: str
    start_local: str
    next: list[NextOccurrence]


class PlaceOut(BaseModel):
    mode: str
    venue_name: str | None
    address: str | None
    online_url: str | None
    latitude: float | None
    longitude: float | None


class CalendarLink(PublicCalendarRef):
    url: str


class ParentLink(BaseModel):
    title: str
    url: str


class PublicEventProps(BaseModel):
    locale: str
    title: str
    summary: str | None
    description_tree: list[Node]
    timezone: str
    all_day: bool
    when: WhenOut | None
    series: SeriesOut | None
    cancelled: bool
    place: PlaceOut
    organiser: str | None
    image: str | None
    category: CategoryRef | None
    calendar: CalendarLink
    parent: ParentLink | None
    sub_events: list[PublicListItem]
    registration_url: str | None
    ics_url: str
    canonical_url: str
    alternates: list[AlternateOut]
    json_ld: Any
    index_in_search: bool
