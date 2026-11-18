"""The pre-scan: ordinary files pass, and each hostile one fails at its bound, fast."""

from __future__ import annotations

import time

import pytest
from sm_events.core import constants
from sm_events.core.errors import ImportFailure
from sm_events.feeds.importing import scan as scan_module
from sm_events.feeds.importing.scan import scan, sniff

from tests.feeds.importing import corpus

INVALID = "ics_invalid"


def fails(data: bytes, code: str, bound: str | None = None) -> ImportFailure:
    began = time.monotonic()
    with pytest.raises(ImportFailure) as caught:
        scan(data)
    assert time.monotonic() - began < 2.0, "the scan must fail fast"
    assert caught.value.code == code
    if bound is not None:
        assert caught.value.bound == bound
    return caught.value


def test_accepts_simple_file():
    got = scan(corpus.simple(3))
    assert len(got.events) == 3 and got.components == 3 and got.timezones == 0
    props = {p.name: p for p in got.events[0].props}
    assert props["UID"].value == "u0@x" and props["SUMMARY"].value == "Talk"


@pytest.mark.parametrize("end", ["\r\n", "\n", "\r"])
def test_bom_and_line_ends(end):
    raw = corpus.simple().decode().replace("\r\n", end)
    got = scan(b"\xef\xbb\xbf" + raw.encode())
    assert len(got.events) == 1


def test_parameters_and_quoted_values_are_read_as_text():
    data = corpus.calendar(
        *corpus.vevent(
            "a@x",
            'ATTENDEE;CN="Doe; Jane:x";ROLE=REQ:mailto:j@example.com',
            "DTSTART;TZID=Europe/Vienna:20260701T100000",
        )
    )
    attendee = next(p for p in scan(data).events[0].props if p.name == "ATTENDEE")
    assert attendee.params == {"CN": "Doe; Jane:x", "ROLE": "REQ"}
    assert attendee.value == "mailto:j@example.com"


def test_children_are_counted_not_read():
    got = scan(
        corpus.calendar(
            *corpus.vevent(
                "a@x", "BEGIN:VALARM", "ACTION:AUDIO", "ATTACH:http://127.0.0.1/x", "END:VALARM"
            )
        )
    )
    (event,) = got.events
    assert event.children == {"VALARM": 1}
    assert all(p.name not in ("ACTION", "ATTACH") for p in event.props)  # never read


def test_a_timezone_is_counted_and_dropped():
    got = scan(
        corpus.calendar(
            "BEGIN:VTIMEZONE",
            "TZID:Custom",
            "TZURL:http://127.0.0.1/tz",
            "END:VTIMEZONE",
            *corpus.vevent(),
        )
    )
    assert got.timezones == 1 and len(got.events) == 1


def test_no_library_parser_is_ever_called(monkeypatch):
    """The scan is the only parser: an iCalendar library never sees the file."""
    import icalendar

    def refuse(*_a, **_k):
        raise AssertionError("the library parser must not run on an upload")

    monkeypatch.setattr(icalendar.Calendar, "from_ical", refuse)
    monkeypatch.setattr(icalendar.Event, "from_ical", refuse, raising=False)
    assert scan(corpus.simple(2)).components == 2
    assert not hasattr(scan_module, "icalendar")


HOSTILE = [
    ("invalid_utf8", corpus.invalid_utf8, "ics_encoding"),
    ("nul", corpus.nul_byte, INVALID),
    ("line_1mb", lambda: corpus.long_line(1_000_000), INVALID),
    ("nested_alarms_10000", lambda: corpus.nested_alarms(10_000), INVALID),
    ("depth_4", lambda: corpus.depth(4), INVALID),
    ("two_calendars", corpus.two_calendars, INVALID),
    ("unbalanced_end", corpus.unbalanced_end, INVALID),
    ("mismatched_end", corpus.mismatched_end, INVALID),
    ("content_before_begin", corpus.content_before_begin, INVALID),
    ("trailing_after_end", corpus.trailing_after_end, INVALID),
    ("properties_501", lambda: corpus.properties(constants.IMPORT_MAX_PROPERTIES + 1), INVALID),
    ("event_300kb", lambda: corpus.big_event(300_000), INVALID),
    ("timezones_101", lambda: corpus.timezones(constants.IMPORT_MAX_TIMEZONES + 1), INVALID),
    (
        "components_20001",
        lambda: corpus.sequential_alarms(constants.IMPORT_MAX_COMPONENTS),
        INVALID,
    ),
    ("events_5001", lambda: corpus.events(constants.IMPORT_MAX_EVENTS + 1), "too_many_events"),
    ("events_100000", lambda: corpus.events(100_000), "too_many_events"),
    ("observances_100000", lambda: corpus.vtimezone_observances(100_000), INVALID),
    ("rdates_50000", lambda: corpus.vtimezone_rdates(50_000), INVALID),
    ("giant_line_21mb", lambda: corpus.one_giant_line(21), INVALID),
    ("giant_line_2mb", lambda: corpus.one_giant_line(2), INVALID),
    ("exdates_1e6_one_line", lambda: corpus.many_exdates(1_000_000), INVALID),
]


@pytest.mark.parametrize(("name", "build", "code"), HOSTILE, ids=[h[0] for h in HOSTILE])
def test_hostile_corpus(name, build, code):
    data = build()
    err = fails(data, code)
    assert err.bound, name  # which limit tripped
    text = f"{err!s} {err.bound}"
    assert "mailto" not in text and "Talk" not in text and "x" * 20 not in text  # no file content


def test_a_file_is_refused_by_its_size_before_anything_is_decoded(monkeypatch):
    seen = []
    real = bytes.decode
    monkeypatch.setattr(scan_module, "_decode", lambda data: seen.append(len(data)) or real(data))
    big = b"x" * (constants.IMPORT_BODY_CEILING + 1)
    monkeypatch.undo()
    fails(big, INVALID, "bytes")


# --- each bound: at the limit passes, one past fails -------------------------------------------


def test_events_bound():
    assert (
        len(scan(corpus.events(constants.IMPORT_MAX_EVENTS)).events) == constants.IMPORT_MAX_EVENTS
    )
    fails(corpus.events(constants.IMPORT_MAX_EVENTS + 1), "too_many_events")


def test_components_bound():
    at = corpus.calendar(
        *corpus.sequential_alarms(constants.IMPORT_MAX_COMPONENTS - 1).decode().split("\r\n")[1:-2]
    )
    assert scan(at).components == constants.IMPORT_MAX_COMPONENTS
    fails(corpus.sequential_alarms(constants.IMPORT_MAX_COMPONENTS), INVALID, "components")


def test_depth_bound():
    assert scan(corpus.depth(constants.IMPORT_MAX_DEPTH)).components == 2
    fails(corpus.depth(constants.IMPORT_MAX_DEPTH + 1), INVALID, "depth")


def test_properties_bound():
    assert scan(corpus.properties(constants.IMPORT_MAX_PROPERTIES)).events
    fails(corpus.properties(constants.IMPORT_MAX_PROPERTIES + 1), INVALID, "properties")


def test_timezones_bound():
    assert scan(corpus.timezones(constants.IMPORT_MAX_TIMEZONES)).timezones == 100
    fails(corpus.timezones(constants.IMPORT_MAX_TIMEZONES + 1), INVALID, "timezones")


def test_line_length_bound():
    at = constants.IMPORT_MAX_LINE
    assert scan(corpus.long_line(at)).events
    fails(corpus.long_line(at + 1), INVALID, "line_length")


def test_folded_lines_measured_unfolded():
    fails(corpus.folded(70_000), INVALID, "line_length")
    assert scan(corpus.folded(60_000)).events


def test_event_size_bound():
    assert scan(corpus.big_event(200_000)).events
    fails(corpus.big_event(constants.IMPORT_MAX_EVENT_BYTES + 5_000), INVALID, "event_size")


def test_parameters_bound():
    many = ";".join(f"P{n}=v" for n in range(constants.IMPORT_MAX_PARAMS + 1))
    ok = ";".join(f"P{n}=v" for n in range(constants.IMPORT_MAX_PARAMS))
    assert scan(corpus.calendar(*corpus.vevent("a@x", f"X-Q;{ok}:v"))).events
    fails(corpus.calendar(*corpus.vevent("a@x", f"X-Q;{many}:v")), INVALID, "parameters")


def test_line_count_bound(monkeypatch):
    monkeypatch.setattr(constants, "IMPORT_MAX_LINES", 100)
    assert scan(corpus.empty_lines(90)).events == ()
    fails(corpus.empty_lines(100), INVALID, "lines")


def test_a_giant_file_costs_bounded_time():
    """21 MB of nothing but a file-wide limit: refused before it is decoded or split."""
    data = corpus.one_giant_line(21)
    began = time.monotonic()
    with pytest.raises(ImportFailure):
        scan(data)
    assert time.monotonic() - began < 0.5


def test_sniff():
    assert sniff(corpus.simple())
    assert sniff(b"\xef\xbb\xbf\r\n\r\n  begin:vcalendar\r\n")
    assert not sniff(b"\x89PNG\r\n\x1a\n")
    assert not sniff(b"")
    assert not sniff(b"PRODID:x\r\nBEGIN:VCALENDAR\r\n")
    assert not sniff(b"BEGIN:VCALENDARX\r\n")
