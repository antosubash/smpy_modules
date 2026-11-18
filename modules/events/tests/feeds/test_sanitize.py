"""Feed text is stripped of control characters, whatever wrote the row."""

from __future__ import annotations

from datetime import UTC, datetime

import icalendar
import pytest
from sm_events.feeds.ics_calendar import build
from sm_events.feeds.ics_event import components
from sm_events.feeds.sanitize import multi_line, single_line

from tests.support.feed_items import make

FIRST, LAST = datetime(2025, 1, 1, tzinfo=UTC), datetime(2027, 12, 31, tzinfo=UTC)
INJECTION = "N\r\nX-EVIL:1"
NASTY = [
    INJECTION,
    "a\nb",
    "a\rb",
    "a\x00b",
    "a\x0bb\x0cc",
    "a\x1bb\x7fc\x85d",
    "a" + chr(0x2028) + "b" + chr(0x2029) + "c",
    "tab\tstays",
]


@pytest.mark.parametrize("raw", NASTY)
def test_single_line_has_no_break_and_no_control(raw):
    out = single_line(raw)
    assert not any(ch in out for ch in "\r\n\x00\x0b\x0c\x1b\x7f\x85" + chr(0x2028) + chr(0x2029))


@pytest.mark.parametrize("raw", NASTY)
def test_multi_line_keeps_only_newline_and_tab(raw):
    out = multi_line(raw)
    assert "\r" not in out and not any(ch in out for ch in "\x00\x0b\x0c\x1b\x7f\x85")
    assert chr(0x2028) not in out and chr(0x2029) not in out


def test_values():
    assert single_line(INJECTION) == "N X-EVIL:1"
    assert multi_line("a\r\nb\rc") == "a\nb\nc"
    assert single_line(None) == "" and multi_line(None) == ""
    assert single_line("tab\tstays") == "tab\tstays"


def lines(raw: bytes) -> list[bytes]:
    return raw.split(b"\r\n")


@pytest.mark.parametrize("raw", NASTY)
def test_every_property_survives(raw):
    item = make(
        text={"title": raw, "slug": "x"},
        venue_name=raw,
        address=raw,
        organiser=raw,
        online_url="https://meet.example/x",
        attendance_mode="hybrid",
        latitude=1.0,
        longitude=2.0,
        category=raw,
        parent_uid=raw,
    )
    item.event.uid = raw  # a row written outside the API
    cal = build([item], name=raw, timezone="Europe/Vienna", first=FIRST, last=LAST)
    assert not any(line.startswith(b"X-EVIL") for line in lines(cal))
    for byte in (b"\x00", b"\x0b", b"\x0c", b"\x1b", b"\x7f"):
        assert byte not in cal
    parsed = icalendar.Calendar.from_ical(cal)
    (event,) = parsed.walk("VEVENT")
    assert "X-EVIL" not in event and "X-EVIL" not in parsed
    assert "\n" not in str(event["SUMMARY"]) and "\r" not in str(event["SUMMARY"])
    assert "\n" not in str(parsed["X-WR-CALNAME"])


def test_injection_through_a_single_event_file_name_and_description():
    item = make(text={"title": INJECTION, "slug": "x"}, organiser=INJECTION)
    raw = components(item)[0].to_ical()
    assert not any(line.startswith(b"X-EVIL") for line in lines(raw))
    ev = icalendar.Event.from_ical(raw)
    assert "X-EVIL" not in ev
    assert "X-EVIL:1" in str(ev["DESCRIPTION"])  # text, on the organiser's own line
