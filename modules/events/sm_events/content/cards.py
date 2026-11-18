"""Event cards: a published public event as another module may show it.

A card is the public projection of one event for a consumer (a newsletter, a block): only what
the anonymous page shows. Callers hand in rows that already came from
:func:`~sm_events.core.access.public.public_events`; the occurrences read is called with the
anonymous principal besides, so a row that is somehow not public still yields no series card.

* a one-off is carded whatever its date, from its own row;
* a series is carded at its **next** occurrence, the first the occurrences read gives over
  ``[now, now + MAX_RANGE_DAYS)`` (one in progress counts, a skipped one never appears, a moved
  one is at its new time, a cancelled one is marked). A series with nothing in that window has
  no card;
* the text is the one in the asked locale, else the default content locale's, else the first
  (:func:`~sm_events.content.public_read.pick_text`), and the paths are in that locale.

The cost is fixed: the texts of every row in one statement, then one occurrences read for all the
series (a second and third only for series the read's own 2,000-item cap left out, at most
:data:`~sm_events.core.constants.CARD_READ_ROUNDS` in all).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from sm_events.calendar.occurrence import Occurrence, OccurrenceFilters
from sm_events.calendar.occurrences import occurrences
from sm_events.calendar.times import Span, all_day_dates
from sm_events.content.public_read import pick_text
from sm_events.content.texts import texts_of
from sm_events.core import constants, locales
from sm_events.core.access.public import ANONYMOUS
from sm_events.core.web_urls import is_web_url
from sm_events.models import Event, EventText
from sm_events.web.endpoints.public import _urls

__all__ = ["EventCard", "cards_for"]

_EVENTS_ONLY = frozenset({constants.SOURCE_EVENTS})


class EventCard(BaseModel):
    """What another module may know of a published event of a public calendar."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    title: str
    summary: str
    """Plain text as the page shows it; ``""`` when there is none."""
    starts_at: datetime
    ends_at: datetime
    """The occurrence's own span, aware UTC (a one-off's: its own)."""
    all_day: bool
    start_date: date | None
    end_date: date | None
    """All-day only, in the event's timezone; ``end_date`` is exclusive."""
    timezone: str
    occurrence_start: datetime | None
    """A series' card: the original start of the occurrence it shows (what ``path`` names)."""
    attendance_mode: str
    venue_name: str
    address: str
    image_url: str
    """An absolute http(s) address as stored, else ``""``."""
    path: str
    ics_path: str
    """Site-relative, locale-prefixed except for the default language."""
    locale: str
    """The language of the text and the paths (not always the one asked for)."""
    cancelled: bool


def _local_day(item: Occurrence, zone: str) -> date | None:
    if item.original_start is None:
        return None
    return item.original_start.astimezone(ZoneInfo(zone)).date()


async def _next_occurrences(
    db: Any, tenant_id: str, series: Sequence[uuid.UUID], now: datetime
) -> dict[uuid.UUID, Occurrence]:
    """The first occurrence at or after ``now`` of each series that has one."""
    found: dict[uuid.UUID, Occurrence] = {}
    pending = set(series)
    for _round in range(constants.CARD_READ_ROUNDS):
        if not pending:
            break
        page = await occurrences(
            db,
            tenant_id=tenant_id,
            viewer=ANONYMOUS,
            start=now,
            end=now + timedelta(days=constants.MAX_RANGE_DAYS),
            filters=OccurrenceFilters(
                event_ids=frozenset(pending),
                include_unpublished=False,
                sources=_EVENTS_ONLY,
            ),
            default_locale=locales.default(),
        )
        for item in page.items:  # ascending: the first one of an event is its next
            if item.event_id in pending and item.end > now:
                found.setdefault(item.event_id, item)
        pending -= found.keys()
        if not page.truncated:
            break  # nothing was left out: what is still pending has no occurrence
    return found


def _card(
    event: Event, text: EventText, item: Occurrence | None, *, series: bool
) -> EventCard | None:
    if series and item is None:
        return None
    start, end = (item.start, item.end) if item else (event.starts_at, event.ends_at)
    first = after = None
    if event.all_day:
        first, after = all_day_dates(Span(start, end), event.timezone)
    day = _local_day(item, event.timezone) if item else None
    cancelled = event.cancelled or (
        item is not None and item.status == constants.OCCURRENCE_CANCELLED
    )
    return EventCard(
        id=event.id,
        title=text.title,
        summary=text.summary or "",
        starts_at=start,
        ends_at=end,
        all_day=event.all_day,
        start_date=first,
        end_date=after,
        timezone=event.timezone,
        occurrence_start=item.original_start if item else None,
        attendance_mode=event.attendance_mode,
        venue_name=event.venue_name or "",
        address=event.address or "",
        image_url=event.image if event.image and is_web_url(event.image) else "",
        path=_urls.event_path(text.slug, text.locale, day),
        ics_path=_urls.event_ics_path(text.slug, text.locale),
        locale=text.locale,
        cancelled=cancelled,
    )


async def cards_for(
    db: Any,
    rows: Sequence[Event],
    *,
    tenant_id: str,
    locale: str | None,
    now: datetime,
) -> list[EventCard]:
    """A card for each of ``rows`` that has one, in the order given. ``rows`` must come from the
    public gate and the tenant must be bound (:func:`~sm_events.core.tenancy.tenant_scope`)."""
    if not rows:
        return []
    default = locales.default()
    texts = await texts_of(db, [row.id for row in rows])
    nexts = await _next_occurrences(db, tenant_id, [r.id for r in rows if r.rrule], now)
    cards: list[EventCard] = []
    for row in rows:
        own = texts.get(row.id)
        if not own:
            continue  # no text, no page to link to
        text = pick_text(own, locale or default, default)
        card = _card(row, text, nexts.get(row.id), series=row.rrule is not None)
        if card is not None:
            cards.append(card)
    return cards
