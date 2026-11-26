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
    HeadOut,
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


class PublicRegistrationOut(BaseModel):
    """Where to register, and for which occurrence. The page is cached and the same for everyone,
    so it carries no seat information of any kind: the registration panel asks live."""

    mode: str
    url: str | None
    """``external`` only: the link."""
    provider: str | None
    target: str | None
    """``builtin`` only: the provider's own name for the form."""
    occurrence_key: str | None
    """The occurrence this page registers for; ``None`` on a series' page with no date chosen."""
    upcoming: list[NextOccurrence]
    """That bare page's next dates to choose from (at most five, none cancelled)."""


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
    type: str
    """The event's type when a plugin on this host provides it, else the default type."""
    public_extra: dict[str, Any]
    """Only what the type declared public (``EventType.public_fields``), never the whole
    ``extra``; ``{}`` for a type that is not installed. Shown as text only."""
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
    registration: PublicRegistrationOut
    ics_url: str
    canonical_url: str
    alternates: list[AlternateOut]
    json_ld: Any
    index_in_search: bool
    head: HeadOut | None = None
    """Set by the endpoint, which resolves it with the values it writes into the head."""
