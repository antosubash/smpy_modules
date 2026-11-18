"""One event, series and overrides as VEVENTs, checked by parsing them back."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import icalendar
import pytest
from sm_events.calendar.times import localize
from sm_events.feeds.ics_event import FeedEvent, components, tzids

from tests.support.feed_items import STAMP, VIENNA, make, override, series_item


def parse(item: FeedEvent) -> list[icalendar.Event]:
    cal = icalendar.Calendar()
    for component in components(item):
        cal.add_component(component)
    return list(icalendar.Calendar.from_ical(cal.to_ical()).walk("VEVENT"))


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


def test_series_with_overrides():
    item = series_item()
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
    item = series_item()
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
    assert "SUMMARY:A\\, B\\; C D \\\\ E" in raw.replace("\r\n ", "")
    assert str(parse(item)[0]["SUMMARY"]) == "A, B; C D \\ E"  # a title is one line


def test_related_to_only_with_parent_uid():
    (child,) = parse(make(parent_uid="parent@simple-module-events"))
    assert str(child["RELATED-TO"]) == "parent@simple-module-events"
    assert child["RELATED-TO"].params["RELTYPE"] == "PARENT"
    (alone,) = parse(make())
    assert "RELATED-TO" not in alone


def test_no_organizer_attendee_alarm():
    item = series_item()
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


def _all_day_series(start: str, end: str, rule: str) -> FeedEvent:
    return make(rule=rule, start=start, end=end, all_day=True)


@pytest.mark.parametrize(
    ("start", "end", "cancelled", "expected_end"),
    [
        ("2026-10-18", "2026-10-18", (2026, 10, 25), date(2026, 10, 26)),  # autumn Sunday, 25 h
        ("2026-03-22", "2026-03-22", (2026, 3, 29), date(2026, 3, 30)),  # spring Sunday, 23 h
        ("2026-03-22", "2026-03-22", (2026, 4, 5), date(2026, 4, 6)),  # the week after
        ("2026-10-17", "2026-10-18", (2026, 10, 24), date(2026, 10, 26)),  # two days across it
        ("2026-03-21", "2026-03-22", (2026, 3, 28), date(2026, 3, 30)),
        ("2026-10-11", "2026-10-13", (2026, 10, 25), date(2026, 10, 28)),  # three days
    ],
)
def test_cancelled_all_day_counts_days_not_hours(start, end, cancelled, expected_end):
    item = _all_day_series(start, end, "FREQ=WEEKLY;COUNT=12")
    day = datetime(*cancelled)
    row = override(item.event, "cancelled", localize(day, VIENNA))
    item = FeedEvent(item.event, item.text, (row,), item.url, None, None)
    _, cancelled_ev = parse(item)
    assert cancelled_ev["DTSTART"].dt == date(*cancelled)
    assert cancelled_ev["DTEND"].dt == expected_end
    assert cancelled_ev["DTEND"].dt > cancelled_ev["DTSTART"].dt
    raw = components(item)[1].to_ical()
    assert f"DTEND;VALUE=DATE:{expected_end:%Y%m%d}".encode() in raw


def test_moved_all_day_over_a_dst_sunday():
    item = _all_day_series("2026-10-18", "2026-10-18", "FREQ=WEEKLY;COUNT=6")
    row = override(
        item.event,
        "moved",
        localize(datetime(2026, 10, 25), VIENNA),
        starts_at=localize(datetime(2026, 10, 26), VIENNA),
        ends_at=localize(datetime(2026, 10, 27), VIENNA),
    )
    item = FeedEvent(item.event, item.text, (row,), item.url, None, None)
    _, moved = parse(item)
    assert moved["RECURRENCE-ID"].dt == date(2026, 10, 25)
    assert (moved["DTSTART"].dt, moved["DTEND"].dt) == (date(2026, 10, 26), date(2026, 10, 27))


@pytest.mark.parametrize(
    ("start", "end"),
    [("2026-03-29", "2026-03-29"), ("2026-10-25", "2026-10-25"), ("2026-03-28", "2026-03-30")],
)
def test_all_day_masters_on_dst_days(start, end):
    item = _all_day_series(start, end, "FREQ=YEARLY;COUNT=2")
    (master,) = parse(item)
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    assert master["DTSTART"].dt == first
    assert master["DTEND"].dt == last + timedelta(days=1)


def test_timed_cancelled_keeps_the_exact_duration_across_dst():
    item = make(rule="FREQ=WEEKLY;COUNT=12", start="2026-03-22T01:30", end="2026-03-22T04:30")
    row = override(item.event, "cancelled", localize(datetime(2026, 3, 29, 1, 30), VIENNA))
    item = FeedEvent(item.event, item.text, (row,), item.url, None, None)
    _, cancelled = parse(item)
    # the master lasts 3 h; on 29 March the clock jumps over 02:00, so 01:30 + 3 h is 05:30 local
    elapsed = cancelled["DTEND"].dt.astimezone(UTC) - cancelled["DTSTART"].dt.astimezone(UTC)
    assert elapsed == timedelta(hours=3)
    assert cancelled["DTEND"].dt.replace(tzinfo=None) == datetime(2026, 3, 29, 5, 30)
