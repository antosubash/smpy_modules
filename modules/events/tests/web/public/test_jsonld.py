"""``Event`` JSON-LD: offsets, statuses, attendance modes, locations."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sm_events.core import constants
from sm_events.web.endpoints.public._jsonld import event_json_ld
from sm_events.web.endpoints.public._occurrence import ShownOccurrence

from tests.support.feed_items import make

URL = "https://example.org/events/concert"


def shown(item, **kw) -> ShownOccurrence:
    event = item.event
    fields = {
        "start": event.starts_at,
        "end": event.ends_at,
        "all_day": event.all_day,
        "start_date": None,
        "end_date": None,
        "status": "scheduled",
        "previous_start": None,
        "date_param": None,
    }
    return ShownOccurrence(**{**fields, **kw})


def ld(item, *occurrences, image=None, locale="en"):
    return event_json_ld(
        event=item.event,
        text=item.text,
        url=URL,
        image=image,
        locale=locale,
        occurrences=occurrences or (shown(item),),
    )


def test_timed_offsets():
    item = make()
    doc = ld(item)
    assert doc["@context"] == "https://schema.org" and doc["@type"] == "Event"
    assert doc["startDate"] == "2026-07-06T10:00:00+02:00"
    assert doc["endDate"] == "2026-07-06T11:30:00+02:00"
    assert doc["name"] == "Concert" and doc["url"] == URL and doc["inLanguage"] == "en"


def test_offset_follows_dst():
    winter = make(start="2026-01-06T10:00", end="2026-01-06T11:00")
    assert ld(winter)["startDate"] == "2026-01-06T10:00:00+01:00"
    utc = make(tz="UTC", start="2026-07-06T08:00", end="2026-07-06T09:00")
    assert ld(utc)["startDate"] == "2026-07-06T08:00:00+00:00"


def test_all_day_inclusive_end():
    item = make(start="2026-08-01", end="2026-08-03", all_day=True)
    occurrence = shown(item, start_date=date(2026, 8, 1), end_date=date(2026, 8, 4))
    doc = ld(item, occurrence)
    assert (doc["startDate"], doc["endDate"]) == ("2026-08-01", "2026-08-03")


def test_status_scheduled_and_cancelled():
    item = make()
    assert ld(item)["eventStatus"] == "https://schema.org/EventScheduled"
    assert (
        ld(item, shown(item, status="cancelled"))["eventStatus"]
        == "https://schema.org/EventCancelled"
    )
    cancelled = make(cancelled=True)
    assert ld(cancelled)["eventStatus"] == "https://schema.org/EventCancelled"


def test_status_rescheduled_previous_start():
    item = make()
    previous = datetime(2026, 7, 5, 8, tzinfo=UTC)
    doc = ld(item, shown(item, status="rescheduled", previous_start=previous))
    assert doc["eventStatus"] == "https://schema.org/EventRescheduled"
    assert doc["previousStartDate"] == "2026-07-05T10:00:00+02:00"


def test_attendance_modes():
    base = "https://schema.org/"
    assert ld(make())["eventAttendanceMode"] == base + "OfflineEventAttendanceMode"
    online = make(attendance_mode="online", online_url="https://meet.example/x")
    assert ld(online)["eventAttendanceMode"] == base + "OnlineEventAttendanceMode"
    hybrid = make(attendance_mode="hybrid", online_url="https://meet.example/x", venue_name="Hall")
    assert ld(hybrid)["eventAttendanceMode"] == base + "MixedEventAttendanceMode"


def test_location_shapes():
    place = make(venue_name="Hall", address="Main St 1", latitude=48.2, longitude=16.37)
    assert ld(place)["location"] == {
        "@type": "Place",
        "name": "Hall",
        "address": {"@type": "PostalAddress", "streetAddress": "Main St 1"},
        "geo": {"@type": "GeoCoordinates", "latitude": 48.2, "longitude": 16.37},
    }
    online = make(attendance_mode="online", online_url="https://meet.example/x")
    assert ld(online)["location"] == {"@type": "VirtualLocation", "url": "https://meet.example/x"}
    hybrid = make(attendance_mode="hybrid", online_url="https://meet.example/x", venue_name="Hall")
    kinds = [loc["@type"] for loc in ld(hybrid)["location"]]
    assert kinds == ["Place", "VirtualLocation"]
    assert "location" not in ld(make())


def test_organizer_and_image_optional():
    plain = ld(make())
    assert "organizer" not in plain and "image" not in plain
    full = ld(make(organiser="Acme"), image="https://example.org/i.jpg")
    assert full["organizer"] == {"@type": "Organization", "name": "Acme"}
    assert full["image"] == "https://example.org/i.jpg"


def test_description_prefers_summary_then_text():
    assert ld(make(text={"summary": "Short"}))["description"] == "Short"
    assert ld(make())["description"] == "Come along"


def test_series_list_bounded():
    item = make(rule="FREQ=DAILY;COUNT=40")
    many = [
        shown(
            item,
            date_param=date(2026, 7, 6 + n),
            start=datetime(2026, 7, 6 + n, 8, tzinfo=UTC),
            end=datetime(2026, 7, 6 + n, 9, tzinfo=UTC),
        )
        for n in range(25)
    ]
    docs = ld(item, *many)
    assert isinstance(docs, list) and len(docs) == constants.NEXT_OCCURRENCES
    assert docs[0]["url"] == f"{URL}?date=2026-07-06"
    assert ld(item, many[0])["url"] == f"{URL}?date=2026-07-06"  # one occurrence: one dict


def test_ended_series_has_no_list():
    item = make(rule="FREQ=DAILY;COUNT=2")
    assert (
        event_json_ld(
            event=item.event, text=item.text, url=URL, image=None, locale="en", occurrences=[]
        )
        == []
    )
