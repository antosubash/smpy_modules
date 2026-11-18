"""What the ``icalendar`` library does with the shapes the feeds emit (Ruling 26)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import icalendar
from sm_events.feeds.ics_tz import vtimezone

VIENNA = ZoneInfo("Europe/Vienna")


def _local(day: int, month: int, hour: int) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=VIENNA)


def _wrap(*components) -> icalendar.Calendar:
    cal = icalendar.Calendar()
    cal.add("prodid", "-//test//EN")
    cal.add("version", "2.0")
    for c in components:
        cal.add_component(c)
    return cal


def _event(uid: str, start, end, **props) -> icalendar.Event:
    ev = icalendar.Event()
    ev.add("uid", uid)
    ev.add("dtstamp", datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")))
    ev.add("dtstart", start)
    ev.add("dtend", end)
    for key, value in props.items():
        ev.add(key, value)
    return ev


def _roundtrip(cal: icalendar.Calendar) -> tuple[bytes, icalendar.Calendar]:
    raw = cal.to_ical()
    return raw, icalendar.Calendar.from_ical(raw)


def test_series_round_trip_vienna():
    master = _event(
        "s@x",
        _local(16, 3, 10),
        _local(16, 3, 11),
        rrule={"FREQ": "WEEKLY", "COUNT": 8},
        exdate=[_local(13, 4, 10)],
    )
    moved = _event(
        "s@x", _local(30, 3, 11), _local(30, 3, 12), **{"recurrence-id": _local(30, 3, 10)}
    )
    cancelled = _event(
        "s@x",
        _local(6, 4, 10),
        _local(6, 4, 11),
        status="CANCELLED",
        **{"recurrence-id": _local(6, 4, 10)},
    )
    zone = vtimezone("Europe/Vienna", datetime(2026, 1, 1), datetime(2026, 12, 31))
    raw, back = _roundtrip(_wrap(zone, master, moved, cancelled))
    text = raw.decode()
    assert text.count("TZID=Europe/Vienna") >= 5

    events = list(back.walk("VEVENT"))
    assert len(events) == 3
    first = events[0]
    assert dict(first["RRULE"]) == {"FREQ": ["WEEKLY"], "COUNT": [8]}
    ex = first["EXDATE"].dts[0].dt
    assert ex.tzinfo.key == "Europe/Vienna" and (ex.hour, ex.day, ex.month) == (10, 13, 4)
    rid = events[1]["RECURRENCE-ID"].dt
    assert rid.tzinfo.key == "Europe/Vienna" and rid.hour == 10 and (rid.day, rid.month) == (30, 3)
    assert events[1]["DTSTART"].dt.hour == 11
    assert events[2]["RECURRENCE-ID"].dt.hour == 10
    assert str(events[2]["STATUS"]) == "CANCELLED"

    (tz,) = back.walk("VTIMEZONE")
    kinds = {c.name for c in tz.subcomponents}
    assert {"STANDARD", "DAYLIGHT"} <= kinds


def test_all_day_round_trip():
    ev = _event(
        "a@x",
        date(2026, 3, 29),
        date(2026, 3, 30),
        rrule={"FREQ": "WEEKLY", "UNTIL": date(2026, 4, 26)},
        exdate=[date(2026, 4, 5)],
    )
    over = _event(
        "a@x", date(2026, 4, 12), date(2026, 4, 13), **{"recurrence-id": date(2026, 4, 12)}
    )
    raw, back = _roundtrip(_wrap(ev, over))
    assert b"DTSTART;VALUE=DATE:20260329" in raw and b"DTEND;VALUE=DATE:20260330" in raw
    first, second = back.walk("VEVENT")
    assert type(first["DTSTART"].dt) is date and type(first["DTEND"].dt) is date
    assert type(first["EXDATE"].dts[0].dt) is date
    assert type(second["RECURRENCE-ID"].dt) is date
    assert first["RRULE"]["UNTIL"] == [date(2026, 4, 26)]


def test_utc_until_and_escaping():
    from zoneinfo import ZoneInfo as Z

    until = datetime(2026, 7, 5, 8, tzinfo=Z("UTC"))
    summary = "Hello, world; line\nbreak " + "ü" * 200
    ev = _event(
        "u@x",
        datetime(2026, 6, 1, 8, tzinfo=Z("UTC")),
        datetime(2026, 6, 1, 9, tzinfo=Z("UTC")),
        rrule={"FREQ": "DAILY", "UNTIL": until},
        summary=summary,
    )
    raw, back = _roundtrip(_wrap(ev))
    (parsed,) = back.walk("VEVENT")
    assert parsed["RRULE"]["UNTIL"][0] == until
    assert str(parsed["SUMMARY"]) == summary
    assert b"UNTIL=20260705T080000Z" in raw
    assert all(len(line) <= 75 for line in raw.split(b"\r\n"))
