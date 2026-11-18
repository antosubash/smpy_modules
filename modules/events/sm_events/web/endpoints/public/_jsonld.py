"""``Event`` structured data for an event page (Ruling 30).

A page of one occurrence (or of a one-off) is one dict; the bare page of a series is a list with
one ``Event`` per upcoming occurrence, at most ``NEXT_OCCURRENCES``. Timed events carry the offset
of the event's own timezone; an all-day event carries dates, the end the inclusive last day. A
cancelled event or occurrence is ``EventCancelled``, a moved one ``EventRescheduled`` with its
``previousStartDate``. Nothing here names a hidden event: the caller passes only what
the page shows.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sm_events.core import constants
from sm_events.feeds.plaintext import to_text
from sm_events.models import Event, EventText
from sm_events.web.endpoints.public._occurrence import ShownOccurrence

__all__ = ["event_json_ld"]

_SCHEMA = "https://schema.org/"
_MODES = {
    "in_person": "OfflineEventAttendanceMode",
    "online": "OnlineEventAttendanceMode",
    "hybrid": "MixedEventAttendanceMode",
}
_DESCRIPTION_MAX = 500


def _local(event: Event, instant: datetime) -> str:
    return instant.astimezone(ZoneInfo(event.timezone)).isoformat()


def _location(event: Event) -> Any:
    out: list[dict[str, Any]] = []
    if (
        event.venue_name
        or event.address
        or (event.latitude is not None and event.longitude is not None)
    ):
        place: dict[str, Any] = {"@type": "Place"}
        if event.venue_name:
            place["name"] = event.venue_name
        if event.address:
            place["address"] = {"@type": "PostalAddress", "streetAddress": event.address}
        if event.latitude is not None and event.longitude is not None:
            place["geo"] = {
                "@type": "GeoCoordinates",
                "latitude": event.latitude,
                "longitude": event.longitude,
            }
        out.append(place)
    if event.online_url and event.attendance_mode != "in_person":
        out.append({"@type": "VirtualLocation", "url": event.online_url})
    if not out:
        return None
    return out[0] if len(out) == 1 else out


def _status(event: Event, occurrence: ShownOccurrence) -> str:
    if event.cancelled or occurrence.status == "cancelled":
        return "EventCancelled"
    return "EventRescheduled" if occurrence.status == "rescheduled" else "EventScheduled"


def _one(
    event: Event, text: EventText, url: str, image: str | None, locale: str, occ: ShownOccurrence
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Event",
        "name": text.title,
        "description": text.summary or to_text(text.description, max_chars=_DESCRIPTION_MAX),
    }
    if occ.all_day and occ.start_date and occ.end_date:
        doc["startDate"] = occ.start_date.isoformat()
        doc["endDate"] = (occ.end_date - timedelta(days=1)).isoformat()
    else:
        doc["startDate"] = _local(event, occ.start)
        doc["endDate"] = _local(event, occ.end)
    status = _status(event, occ)
    doc["eventStatus"] = _SCHEMA + status
    if status == "EventRescheduled" and occ.previous_start is not None:
        doc["previousStartDate"] = _local(event, occ.previous_start)
    doc["eventAttendanceMode"] = _SCHEMA + _MODES.get(event.attendance_mode, _MODES["in_person"])
    if (location := _location(event)) is not None:
        doc["location"] = location
    if event.organiser:
        doc["organizer"] = {"@type": "Organization", "name": event.organiser}
    if image:
        doc["image"] = image
    day: date | None = occ.date_param
    doc["url"] = f"{url}?date={day.isoformat()}" if day else url
    doc["inLanguage"] = locale
    return doc


def event_json_ld(
    *,
    event: Event,
    text: EventText,
    url: str,
    image: str | None,
    locale: str,
    occurrences: Sequence[ShownOccurrence],
) -> dict[str, Any] | list[dict[str, Any]]:
    """One ``Event`` for one occurrence; a list (bounded) for several; ``[]`` for none."""
    if len(occurrences) == 1:
        return _one(event, text, url, image, locale, occurrences[0])
    shown = occurrences[: constants.NEXT_OCCURRENCES]
    return [_one(event, text, url, image, locale, occ) for occ in shown]
