"""One event, series and overrides as VEVENTs, checked by parsing them back."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import icalendar
from sm_events.calendar import rrule
from sm_events.calendar.times import localize, to_span
from sm_events.feeds.ics_event import FeedEvent, components, tzids
from sm_events.models import Event, EventText, OccurrenceOverride

VIENNA = ZoneInfo("Europe/Vienna")
STAMP = datetime(2026, 5, 1, 12, 30, tzinfo=UTC)


def make(
    *,
    start="2026-07-06T10:00",
    end="2026-07-06T11:30",
    tz="Europe/Vienna",
    all_day=False,
    rule: str | None = None,
    overrides=(),
    text: dict | None = None,
    url="https://example.org/events/concert",
    category=None,
    parent_uid=None,
    **fields,
) -> FeedEvent:
    span = to_span(all_day=all_day, timezone=tz, start=start, end=end, recurring=rule is not None)
    parsed = rrule.parse(rule, all_day=all_day, timezone=tz) if rule else None
    event = Event(
        id=uuid.uuid4(),
        uid=f"{uuid.uuid4()}@simple-module-events",
        calendar_id=uuid.uuid4(),
        starts_at=span.starts_at,
        ends_at=span.ends_at,
        timezone=tz,
        all_day=all_day,
        rrule=parsed.text if parsed else None,
        revision=fields.pop("revision", 7),
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
        updated_at=STAMP,
        status="published",
        **fields,
    )
    fields_text = {"title": "Concert", "slug": "concert", "summary": None, **(text or {})}
    return FeedEvent(
        event=event,
        text=EventText(
            event_id=event.id, locale="en", description="<p>Come along</p>", **fields_text
        ),
        overrides=tuple(overrides),
        url=url,
        category=category,
        parent_uid=parent_uid,
    )


def parse(item: FeedEvent) -> list[icalendar.Event]:
    cal = icalendar.Calendar()
    for component in components(item):
        cal.add_component(component)
    return list(icalendar.Calendar.from_ical(cal.to_ical()).walk("VEVENT"))


def override(item_event: Event, kind: str, original: datetime, **kw) -> OccurrenceOverride:
    return OccurrenceOverride(event_id=item_event.id, original_start=original, kind=kind, **kw)


def test_one_off_timed():
    (ev,) = parse(make())
    item_uid = str(ev["UID"])
    assert item_uid.endswith("@simple-module-events")
    start, end = ev["DTSTART"].dt, ev["DTEND"].dt
    assert start.tzinfo.key == "Europe/Vienna" and end.tzinfo.key == "Europe/Vienna"
    assert start.replace(tzinfo=None) == datetime(2026, 7, 6, 10)
    assert end.replace(tzinfo=None) == datetime(2026, 7, 6, 11, 30)
    assert int(ev["SEQUENCE"]) == 7
    assert ev["DTSTAMP"].dt == STAMP and ev["LAST-MODIFIED"].dt == STAMP
    assert ev["CREATED"].dt == datetime(2026, 4, 1, tzinfo=UTC)
    assert str(ev["URL"]) == "https://example.org/events/concert"
    assert str(ev["SUMMARY"]) == "Concert"
    assert str(ev["DESCRIPTION"]) == "Come along"
    assert str(ev["STATUS"]) == "CONFIRMED"


def test_uid_is_the_stored_uid_verbatim():
    item = make()
    (ev,) = parse(item)
    assert str(ev["UID"]) == item.event.uid


def test_all_day_dates():
    item = make(start="2026-03-29", end="2026-03-29", all_day=True)
    (ev,) = parse(item)
    assert ev["DTSTART"].dt == date(2026, 3, 29) and type(ev["DTSTART"].dt) is date
    assert ev["DTEND"].dt == date(2026, 3, 30) and type(ev["DTEND"].dt) is date
    raw = components(item)[0].to_ical()
    assert b"DTSTART;VALUE=DATE:20260329" in raw and b"DTEND;VALUE=DATE:20260330" in raw
    assert b"TZID" not in raw


def test_utc_event_has_no_tzid():
    item = make(tz="UTC", start="2026-07-06T08:00", end="2026-07-06T09:00")
    raw = components(item)[0].to_ical()
    assert b"DTSTART:20260706T080000Z" in raw and b"TZID" not in raw
    assert tzids([item]) == set()


def test_tzids_lists_timed_named_zones_only():
    ny = make(tz="America/New_York")
    vienna_all_day = make(start="2026-03-29", end="2026-03-29", all_day=True)
    assert tzids([make(), ny, vienna_all_day, make(tz="UTC")]) == {
        "Europe/Vienna",
        "America/New_York",
    }


def _series_item() -> FeedEvent:
    base = make(rule="FREQ=WEEKLY;COUNT=8", start="2026-03-16T10:00", end="2026-03-16T11:00")
    event = base.event

    def week(n: int) -> datetime:
        return localize(datetime(2026, 3, 16, 10) + timedelta(weeks=n - 1), VIENNA)

    return FeedEvent(
        event=event,
        text=base.text,
        overrides=(
            override(event, "skipped", week(5)),
            override(
                event,
                "moved",
                week(3),
                starts_at=week(3) + timedelta(hours=1),
                ends_at=week(3) + timedelta(hours=2),
            ),
            override(event, "cancelled", week(4)),
        ),
        url=base.url,
        category=None,
        parent_uid=None,
    )


def test_series_with_overrides():
    item = _series_item()
    master, moved, cancelled = parse(item)
    assert master["RRULE"].to_ical().decode() == item.event.rrule
    (exdate,) = master["EXDATE"].dts
    assert exdate.dt.replace(tzinfo=None) == datetime(2026, 4, 13, 10)
    assert exdate.dt.tzinfo.key == "Europe/Vienna"
    assert "RECURRENCE-ID" not in master

    rid = moved["RECURRENCE-ID"].dt
    assert (
        rid.replace(tzinfo=None) == datetime(2026, 3, 30, 10) and rid.tzinfo.key == "Europe/Vienna"
    )
    assert moved["DTSTART"].dt.replace(tzinfo=None) == datetime(2026, 3, 30, 11)
    assert moved["DTEND"].dt.replace(tzinfo=None) == datetime(2026, 3, 30, 12)
    assert str(moved["UID"]) == str(master["UID"])
    assert int(moved["SEQUENCE"]) == int(master["SEQUENCE"])
    assert str(moved["STATUS"]) == "CONFIRMED"

    assert cancelled["RECURRENCE-ID"].dt.replace(tzinfo=None) == datetime(2026, 4, 6, 10)
    assert str(cancelled["STATUS"]) == "CANCELLED"
    assert cancelled["DTSTART"].dt.replace(tzinfo=None) == datetime(2026, 4, 6, 10)
    assert cancelled["DTEND"].dt.replace(tzinfo=None) == datetime(2026, 4, 6, 11)
    assert str(cancelled["SUMMARY"]) == "Concert"


def test_overrides_come_after_the_master_by_original_start():
    item = _series_item()
    names = [
        str(c.get("RECURRENCE-ID").dt) if c.get("RECURRENCE-ID") else "" for c in components(item)
    ]
    assert names[0] == "" and names[1:] == sorted(names[1:])


def test_all_day_series_exdate_is_date():
    base = make(rule="FREQ=WEEKLY;COUNT=4", start="2026-03-29", end="2026-03-29", all_day=True)
    event = base.event
    skipped = override(event, "skipped", localize(datetime(2026, 4, 5), VIENNA))
    moved = override(
        event,
        "moved",
        localize(datetime(2026, 4, 12), VIENNA),
        starts_at=localize(datetime(2026, 4, 14), VIENNA),
        ends_at=localize(datetime(2026, 4, 15), VIENNA),
    )
    item = FeedEvent(event, base.text, (skipped, moved), base.url, None, None)
    master, moved_ev = parse(item)
    assert master["EXDATE"].dts[0].dt == date(2026, 4, 5)
    assert type(master["EXDATE"].dts[0].dt) is date
    assert moved_ev["RECURRENCE-ID"].dt == date(2026, 4, 12)
    assert moved_ev["DTSTART"].dt == date(2026, 4, 14) and moved_ev["DTEND"].dt == date(2026, 4, 15)


def test_utc_until_survives():
    item = make(rule="FREQ=DAILY;UNTIL=20260710T080000Z", tz="Europe/Vienna")
    (ev,) = parse(item)
    assert b"UNTIL=20260710T080000Z" in ev["RRULE"].to_ical()


def test_cancelled_event_status():
    (ev,) = parse(make(cancelled=True))
    assert str(ev["STATUS"]) == "CANCELLED"


def test_location_geo_categories():
    (ev,) = parse(
        make(
            venue_name="Konzerthaus",
            address="Lothringerstr. 20",
            latitude=48.2,
            longitude=16.37,
            category="Music",
        )
    )
    assert str(ev["LOCATION"]) == "Konzerthaus, Lothringerstr. 20"
    assert (ev["GEO"].latitude, ev["GEO"].longitude) == (48.2, 16.37)
    assert ev["CATEGORIES"].cats == ["Music"]
    (online,) = parse(make(attendance_mode="online", online_url="https://meet.example/x"))
    assert str(online["LOCATION"]) == "https://meet.example/x" and "GEO" not in online
    (half,) = parse(make(latitude=48.2))
    assert "GEO" not in half
    (bare,) = parse(make())
    assert "LOCATION" not in bare and "CATEGORIES" not in bare


def test_description_lines():
    (ev,) = parse(
        make(
            organiser="Acme Org",
            online_url="https://meet.example/x",
            attendance_mode="hybrid",
            venue_name="Hall",
        )
    )
    lines = str(ev["DESCRIPTION"]).split("\n")
    assert lines[0] == "Come along"
    assert "Organiser: Acme Org" in lines and "https://meet.example/x" in lines
    assert str(ev["LOCATION"]) == "Hall"


def test_special_characters_are_escaped_by_the_library():
    item = make(text={"title": "A, B; C\nD \\ E", "slug": "x"})
    raw = components(item)[0].to_ical().decode()
    assert "SUMMARY:A\\, B\\; C\\nD \\\\ E" in raw.replace("\r\n ", "")
    assert str(parse(item)[0]["SUMMARY"]) == "A, B; C\nD \\ E"


def test_related_to_only_with_parent_uid():
    (child,) = parse(make(parent_uid="parent@simple-module-events"))
    assert str(child["RELATED-TO"]) == "parent@simple-module-events"
    assert child["RELATED-TO"].params["RELTYPE"] == "PARENT"
    (alone,) = parse(make())
    assert "RELATED-TO" not in alone


def test_no_organizer_attendee_alarm():
    item = _series_item()
    for ev in parse(item):
        assert "ORGANIZER" not in ev and "ATTENDEE" not in ev
        assert not list(ev.walk("VALARM"))
    cal = icalendar.Calendar()
    for c in components(item):
        cal.add_component(c)
    assert "METHOD" not in cal


def test_dtstamp_falls_back_to_created_at():
    item = make()
    item.event.updated_at = None
    (ev,) = parse(item)
    assert ev["DTSTAMP"].dt == datetime(2026, 4, 1, tzinfo=UTC)
