"""The calendar file: properties, one VTIMEZONE per zone, deterministic bytes."""

from __future__ import annotations

from datetime import UTC, datetime

import icalendar
from sm_events.feeds.ics_calendar import build

from tests.support.feed_items import make, series_item

FIRST, LAST = datetime(2025, 1, 1, tzinfo=UTC), datetime(2027, 12, 31, tzinfo=UTC)


def calendar(items, **kw) -> tuple[bytes, icalendar.Calendar]:
    raw = build(items, name="Team & Co", timezone="Europe/Vienna", first=FIRST, last=LAST, **kw)
    return raw, icalendar.Calendar.from_ical(raw)


def test_calendar_properties():
    raw, cal = calendar([make()])
    assert str(cal["PRODID"]) == "-//simple-module//events//EN"
    assert str(cal["VERSION"]) == "2.0" and str(cal["CALSCALE"]) == "GREGORIAN"
    assert str(cal["X-WR-CALNAME"]) == "Team & Co"
    assert str(cal["X-WR-TIMEZONE"]) == "Europe/Vienna"
    assert b"REFRESH-INTERVAL;VALUE=DURATION:PT1H" in raw
    assert b"X-PUBLISHED-TTL:PT1H" in raw
    assert "METHOD" not in cal
    assert raw.startswith(b"BEGIN:VCALENDAR\r\n") and raw.endswith(b"END:VCALENDAR\r\n")


def test_one_vtimezone_per_zone():
    items = [
        make(),
        make(start="2026-07-07T10:00", end="2026-07-07T11:00"),
        make(tz="America/New_York"),
    ]
    _, cal = calendar(items)
    assert sorted(str(z["TZID"]) for z in cal.walk("VTIMEZONE")) == [
        "America/New_York",
        "Europe/Vienna",
    ]
    _, utc_only = calendar([make(tz="UTC", start="2026-07-06T08:00", end="2026-07-06T09:00")])
    assert not list(utc_only.walk("VTIMEZONE"))
    _, all_day = calendar([make(start="2026-03-29", end="2026-03-29", all_day=True)])
    assert not list(all_day.walk("VTIMEZONE"))


def test_vtimezone_covers_an_old_series_start():
    old = make(start="2020-03-02T10:00", end="2020-03-02T11:00", rule="FREQ=WEEKLY;COUNT=500")
    _, cal = calendar([old])
    (zone,) = cal.walk("VTIMEZONE")
    years = {c["DTSTART"].dt.year for c in zone.subcomponents}
    assert min(years) <= 2020


def test_deterministic():
    items = [series_item(), make(start="2026-06-01T10:00", end="2026-06-01T11:00")]
    assert build(items, name="n", timezone="UTC", first=FIRST, last=LAST) == build(
        list(reversed(items)), name="n", timezone="UTC", first=FIRST, last=LAST
    )


def test_components_ordered_by_start_uid_recurrence_id():
    late = make(start="2026-09-01T10:00", end="2026-09-01T11:00")
    early = make(start="2026-01-01T10:00", end="2026-01-01T11:00")
    series = series_item()
    _, cal = calendar([late, series, early])
    events = list(cal.walk("VEVENT"))
    uids = [str(e["UID"]) for e in events]
    assert uids[0] == str(early.event.uid) and uids[-1] == str(late.event.uid)
    mine = [e for e in events if str(e["UID"]) == series.event.uid]
    assert "RECURRENCE-ID" not in mine[0]
    assert [e["RECURRENCE-ID"].dt for e in mine[1:]] == sorted(
        e["RECURRENCE-ID"].dt for e in mine[1:]
    )


def test_empty_feed_is_a_valid_calendar():
    _, cal = calendar([])
    assert not list(cal.walk("VEVENT")) and str(cal["VERSION"]) == "2.0"


def test_every_line_is_folded_and_crlf():
    long = make(text={"title": "T" * 300, "slug": "t"})
    raw, _ = calendar([long])
    assert b"\n" not in raw.replace(b"\r\n", b"")
    assert all(len(line) <= 75 for line in raw.split(b"\r\n"))
