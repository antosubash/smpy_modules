"""The one-line description an event page falls back to when its author wrote none.

``<meta name="description">`` is what a search result and a link preview show, and an event with
no summary, description or SEO text would otherwise have none. The line is built from what the page
already says (the date and time on the event's own clock, the place, the calendar) in the page's
language, and goes through the same escaping as every other meta tag.
"""

from __future__ import annotations

from datetime import datetime

from sm_events.web.schemas.public_event import PublicEventProps

__all__ = ["fallback_description"]

_DATE = {"en": "%b %d, %Y", "de": "%d.%m.%Y"}
_ALL_DAY = {"en": "All day", "de": "Ganztägig"}


def _stamp(local: str) -> datetime:
    return datetime.fromisoformat(local)


def _clock(moment: datetime, locale: str) -> str:
    if locale == "en":
        return moment.strftime("%I:%M %p").lstrip("0")
    return moment.strftime("%H:%M")


def _when(props: PublicEventProps) -> str | None:
    when = props.when
    if when is None:
        return None
    locale = props.locale
    pattern = _DATE.get(locale, "%Y-%m-%d")
    start = _stamp(when.start_local)
    day = (
        start.strftime(pattern).replace(" 0", " ", 1) if locale == "en" else start.strftime(pattern)
    )
    if when.all_day:
        return f"{day}, {_ALL_DAY.get(locale, _ALL_DAY['en'])}"
    end = _stamp(when.end_local)
    return f"{day}, {_clock(start, locale)} {chr(0x2013)} {_clock(end, locale)} ({props.timezone})"


def fallback_description(props: PublicEventProps) -> str | None:
    """Date and time, place and calendar name, joined; ``None`` only if there is none of them."""
    place = props.place.venue_name or props.place.address
    parts = [_when(props), " ".join((place or "").split()) or None, props.calendar.name]
    line = " · ".join(part for part in parts if part)
    return line or None
