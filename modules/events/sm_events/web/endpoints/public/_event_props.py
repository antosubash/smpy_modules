"""The props of an event page, and the validator that goes with them.

Everything is read through the gate: the event came from ``event_by_slug``, its calendar from
``public_calendars()``, its sub-events and parent from ``public_children`` and ``public_parent``,
its category from ``public_categories()``. A child of a hidden parent shows no parent anywhere
(page, head, JSON-LD); a parent lists only its publicly visible children.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from sm_events.calendar.times import Span, to_local
from sm_events.content.public_read import (
    pick_text,
)
from sm_events.content.richtext_tree import to_tree
from sm_events.core import locales
from sm_events.feeds.plaintext import to_text
from sm_events.models import Event
from sm_events.web.endpoints.public import _urls
from sm_events.web.endpoints.public._event_context import EventContext
from sm_events.web.endpoints.public._jsonld import event_json_ld
from sm_events.web.endpoints.public._listing import category_name, make_item
from sm_events.web.endpoints.public._occurrence import ShownOccurrence, own_occurrence
from sm_events.web.schemas.public import AlternateOut, CategoryRef, PublicListItem
from sm_events.web.schemas.public_event import (
    CalendarLink,
    NextOccurrence,
    ParentLink,
    PlaceOut,
    PublicEventProps,
    SeriesOut,
    WhenOut,
)

__all__ = ["build_props", "description_for_head", "web_url"]

_META_DESCRIPTION_MAX = 160
_WEB = frozenset({"http", "https"})


def web_url(value: str | None) -> str | None:
    """``value`` when it is an absolute ``http(s)`` URL, else ``None``: a stored address is shown
    only as a link a browser may follow."""
    if not value:
        return None
    parts = urlsplit(value)
    return value if parts.scheme in _WEB and parts.netloc else None


def _local(event: Event, start: datetime, end: datetime) -> tuple[str, str]:
    return to_local(Span(start, end), all_day=event.all_day, timezone=event.timezone)


def _when(event: Event, shown: ShownOccurrence) -> WhenOut:
    start_local, end_local = _local(event, shown.start, shown.end)
    previous = None
    if shown.previous_start is not None:
        previous = _local(event, shown.previous_start, shown.previous_start)[0]
    return WhenOut(
        start=shown.start,
        end=shown.end,
        all_day=event.all_day,
        start_local=start_local,
        end_local=end_local,
        start_date=shown.start_date,
        end_date=shown.end_date,
        status=shown.status,
        previous_start_local=previous,
        date_param=shown.date_param,
    )


def _alternates(request_origin: Any, ctx: EventContext) -> list[AlternateOut]:
    """``hreflang`` for the languages this event has a text in and the site serves, plus
    ``x-default``; none when the event has a single language."""
    served = [loc for loc in locales.supported() if loc in ctx.texts]
    if len(served) < 2:
        return []
    out = [
        AlternateOut(locale=loc, url=request_origin(_urls.event_path(ctx.texts[loc].slug, loc)))
        for loc in served
    ]
    default = locales.default() if locales.default() in ctx.texts else served[0]
    return [
        *out,
        AlternateOut(
            locale="x-default",
            url=request_origin(_urls.event_path(ctx.texts[default].slug, default)),
        ),
    ]


def _sub_items(ctx: EventContext) -> list[PublicListItem]:
    items: list[PublicListItem] = []
    for child in ctx.children:
        texts = ctx.child_texts.get(child.id)
        calendar = ctx.child_calendars.get(child.calendar_id)
        if not texts or calendar is None:
            continue
        text = pick_text(texts, ctx.locale, locales.default())
        items.append(
            make_item(
                key=text.slug,
                event=child,
                text=text,
                calendar=calendar,
                category=None,
                locale=ctx.locale,
                default_locale=locales.default(),
                span=Span(child.starts_at, child.ends_at),
                day=None,
                status="cancelled" if child.cancelled else "scheduled",
                rescheduled=False,
            )
        )
    return items


def build_props(
    ctx: EventContext, shown: ShownOccurrence | None, upcoming: list[ShownOccurrence], origin: Any
) -> PublicEventProps:
    """The page's props. ``shown`` is the occurrence a ``?date=`` named (``None`` for a one-off's
    own time or a series' bare page); ``upcoming`` are a series' next occurrences; ``origin`` turns
    a path into an absolute URL."""
    event, text, locale = ctx.event, ctx.text, ctx.locale
    series = event.rrule is not None
    if shown is None and not series:
        shown = own_occurrence(event)  # a one-off: its own span is the one occurrence
    cancelled = event.cancelled or (shown is not None and shown.status == "cancelled")
    day: date | None = shown.date_param if shown else None
    url = origin(_urls.event_path(text.slug, locale))
    canonical = origin(_urls.event_path(text.slug, locale, day))
    image = web_url(event.image)
    ld_occurrences = [shown] if shown is not None else upcoming
    json_ld = event_json_ld(
        event=event, text=text, url=url, image=image, locale=locale, occurrences=ld_occurrences
    )
    next_items = [
        NextOccurrence(
            date_param=o.date_param,
            url=_urls.event_path(text.slug, locale, o.date_param),
            start_local=_local(event, o.start, o.end)[0],
            end_local=_local(event, o.start, o.end)[1],
            status=o.status,
        )
        for o in upcoming
    ]
    return PublicEventProps(
        locale=locale,
        title=text.title,
        summary=text.summary,
        description_tree=to_tree(text.description),
        timezone=event.timezone,
        all_day=event.all_day,
        when=_when(event, shown) if shown is not None else None,
        series=SeriesOut(
            rule=event.rrule,  # type: ignore[arg-type]
            start_local=_local(event, event.starts_at, event.ends_at)[0],
            next=next_items,
        )
        if series and shown is None
        else None,
        cancelled=cancelled,
        place=PlaceOut(
            mode=event.attendance_mode,
            venue_name=event.venue_name,
            address=event.address,
            online_url=web_url(event.online_url),
            latitude=event.latitude,
            longitude=event.longitude,
        ),
        organiser=event.organiser,
        image=image,
        category=None
        if ctx.category is None
        else CategoryRef(
            slug=ctx.category.slug,
            name=category_name(ctx.category, locale, locales.default()),
            color=ctx.category.color,
        ),
        calendar=CalendarLink(
            slug=ctx.calendar.slug,
            name=ctx.calendar.name,
            color=ctx.calendar.color,
            url=_urls.calendar_path(ctx.calendar.slug, locale),
        ),
        parent=None
        if ctx.parent is None or ctx.parent_text is None
        else ParentLink(
            title=ctx.parent_text.title,
            url=_urls.event_path(ctx.parent_text.slug, ctx.parent_text.locale),
        ),
        sub_events=_sub_items(ctx),
        registration_url=None if cancelled else web_url(event.registration_url),
        ics_url=_urls.event_ics_path(text.slug, locale),
        canonical_url=canonical,
        alternates=_alternates(origin, ctx),
        json_ld=json_ld or None,
        index_in_search=not text.noindex,
    )


def description_for_head(ctx: EventContext) -> str | None:
    text = ctx.text
    return (
        text.seo_description
        or text.summary
        or to_text(text.description, max_chars=_META_DESCRIPTION_MAX)
        or None
    )
