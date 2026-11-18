"""One event, with its overrides, as ``VEVENT`` components (Rulings 26 and 27).

Built only with ``icalendar``, which escapes text, folds lines and writes CRLF; no value is
concatenated into iCalendar syntax here. Nothing here re-expands a rule: a series is the
master (``RRULE`` plus an ``EXDATE`` per skipped occurrence) and one ``VEVENT`` with the same
``UID`` and a ``RECURRENCE-ID`` per moved or cancelled one, and the client expands.

Times: a timed event's ``DTSTART``/``DTEND``/``EXDATE``/``RECURRENCE-ID`` are the stored UTC
instants shown in the event's own zone as ``TZID=<zone>`` (the file carries one ``VTIMEZONE``
per zone, :mod:`~sm_events.feeds.ics_tz`); a UTC event's are ``...Z``; an all-day event's are
``VALUE=DATE`` with an exclusive ``DTEND``. The rule is the stored normalised text (a timed
``UNTIL`` already UTC, an all-day ``UNTIL`` a date).

No ``ORGANIZER`` (it needs a ``mailto:`` address and makes clients treat the event as an
invitation), no ``ATTENDEE``, no ``VALARM``, no ``METHOD``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import icalendar

from sm_events.calendar.times import Span, all_day_dates
from sm_events.feeds.plaintext import to_text
from sm_events.models import Event, EventText, OccurrenceOverride, OverrideKind

__all__ = ["FeedEvent", "components", "tzids"]

_UTC = "UTC"


@dataclass(frozen=True)
class FeedEvent:
    """What the feed read hands over; no ORM session past this point."""

    event: Event
    text: EventText  # already picked per Ruling 12
    overrides: Sequence[OccurrenceOverride]
    url: str  # the absolute public URL
    category: str | None  # the category's name in the feed's language
    parent_uid: str | None  # only when the parent is public


def tzids(items: Iterable[FeedEvent]) -> set[str]:
    """The named zones timed events use: each needs a ``VTIMEZONE`` (UTC needs none)."""
    return {i.event.timezone for i in items if not i.event.all_day and i.event.timezone != _UTC}


def _when(event: Event, instant: datetime) -> datetime:
    """``instant`` as the event's own wall clock (aware in its zone; ``UTC`` stays UTC)."""
    if event.timezone == _UTC:
        return instant.astimezone(UTC)
    return instant.astimezone(ZoneInfo(event.timezone))


def _day(event: Event, instant: datetime) -> date:
    return instant.astimezone(ZoneInfo(event.timezone)).date()


def _stamp(event: Event) -> datetime:
    return (event.updated_at or event.created_at).astimezone(UTC)


def _description(item: FeedEvent) -> str | None:
    lines = [to_text(item.text.description)]
    if item.event.organiser:
        lines.append(f"Organiser: {item.event.organiser}")
    if item.event.online_url:
        lines.append(item.event.online_url)
    joined = "\n".join(line for line in lines if line)
    return joined or None


def _location(event: Event) -> str | None:
    place = ", ".join(part for part in (event.venue_name, event.address) if part)
    return place or event.online_url


def _common(item: FeedEvent) -> icalendar.Event:
    event, text = item.event, item.text
    out = icalendar.Event()
    out.add("uid", event.uid)
    out.add("sequence", event.revision)
    out.add("dtstamp", _stamp(event))
    out.add("last-modified", _stamp(event))
    out.add("created", event.created_at.astimezone(UTC))
    out.add("summary", text.title)
    if description := _description(item):
        out.add("description", description)
    if location := _location(event):
        out.add("location", location)
    if event.latitude is not None and event.longitude is not None:
        out.add("geo", (event.latitude, event.longitude))
    out.add("url", item.url)
    if item.category:
        out.add("categories", [item.category])
    if item.parent_uid:
        out.add("related-to", item.parent_uid, parameters={"RELTYPE": "PARENT"})
    return out


def _span(item: FeedEvent, out: icalendar.Event, span: Span) -> None:
    event = item.event
    if event.all_day:
        first, after = all_day_dates(span, event.timezone)
        out.add("dtstart", first)
        out.add("dtend", after)
    else:
        out.add("dtstart", _when(event, span.starts_at))
        out.add("dtend", _when(event, span.ends_at))


def _recurrence_id(event: Event, original: datetime) -> date | datetime:
    return _day(event, original) if event.all_day else _when(event, original)


def _master(item: FeedEvent) -> icalendar.Event:
    event = item.event
    out = _common(item)
    _span(item, out, Span(event.starts_at, event.ends_at))
    out.add("status", "CANCELLED" if event.cancelled else "CONFIRMED")
    if event.rrule:
        out.add("rrule", icalendar.vRecur.from_ical(event.rrule))
        skipped = [
            _recurrence_id(event, o.original_start)
            for o in sorted(item.overrides, key=lambda o: o.original_start)
            if o.kind == OverrideKind.SKIPPED.value
        ]
        if skipped:
            out.add("exdate", skipped)
    return out


def _override(item: FeedEvent, row: OccurrenceOverride) -> icalendar.Event:
    event = item.event
    out = _common(item)
    out.add("recurrence-id", _recurrence_id(event, row.original_start))
    if row.kind == OverrideKind.MOVED.value and row.starts_at and row.ends_at:
        _span(item, out, Span(row.starts_at, row.ends_at))
        out.add("status", "CONFIRMED")
    else:
        # A cancelled instance keeps its original time and says so.
        length = event.ends_at - event.starts_at
        _span(item, out, Span(row.original_start, row.original_start + length))
        out.add("status", "CANCELLED")
    return out


def components(item: FeedEvent) -> list[Any]:
    """The master first, then one component per moved or cancelled occurrence, by original
    start. A skipped occurrence is only an ``EXDATE`` on the master."""
    out = [_master(item)]
    shown = (OverrideKind.MOVED.value, OverrideKind.CANCELLED.value)
    if item.event.rrule:
        rows = sorted(
            (o for o in item.overrides if o.kind in shown), key=lambda o: o.original_start
        )
        out.extend(_override(item, row) for row in rows)
    return out
