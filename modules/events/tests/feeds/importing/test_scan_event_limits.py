"""Per-event limits skip the event, never the file; the skip is as cheap as the scan."""

from __future__ import annotations

import time

from sm_events.core import constants
from sm_events.feeds.importing.scan import scan

from tests.feeds.importing import corpus

# --- per-event limits skip the event, never the file --------------------------------------------


def _only(data: bytes):
    scanned = scan(data)
    assert len(scanned.events) >= 1
    return scanned.events


def test_properties_per_event_at_the_limit_pass_one_past_skips_that_event():
    assert _only(corpus.properties(constants.IMPORT_MAX_PROPERTIES))[0].refused is None
    event = _only(corpus.properties(constants.IMPORT_MAX_PROPERTIES + 1))[0]
    assert event.refused == "too_many_properties"
    assert event.position == 1 and {p.name for p in event.props} <= {"UID", "SUMMARY"}


def test_event_bytes_at_the_limit_pass_one_past_skips_that_event():
    assert _only(corpus.big_event(200_000))[0].refused is None
    assert _only(corpus.big_event(constants.IMPORT_MAX_EVENT_BYTES + 5_000))[0].refused == (
        "event_too_large"
    )


def test_parameters_per_property_at_the_limit_pass_one_past_skips_that_event():
    many = ";".join(f"P{n}=v" for n in range(constants.IMPORT_MAX_PARAMS + 1))
    ok = ";".join(f"P{n}=v" for n in range(constants.IMPORT_MAX_PARAMS))
    assert _only(corpus.calendar(*corpus.vevent("a@x", f"X-Q;{ok}:v")))[0].refused is None
    got = _only(corpus.calendar(*corpus.vevent("a@x", f"X-Q;{many}:v")))[0]
    assert got.refused == "too_many_parameters"


def test_attendees_per_event_at_the_limit_pass_one_past_skips_that_event():
    assert _only(corpus.with_event_lines(constants.IMPORT_MAX_ATTENDEES))[0].refused is None
    got = _only(corpus.with_event_lines(constants.IMPORT_MAX_ATTENDEES + 1))[0]
    assert got.refused == "too_many_attendees"


def test_the_events_around_a_refused_one_are_kept_with_their_positions():
    big = corpus.vevent("big@x", "SUMMARY:Huge", *[f"X-P{n}:v" for n in range(600)])
    data = corpus.calendar(*corpus.vevent("a@x"), *big, *corpus.vevent("c@x"))
    events = scan(data).events
    assert [(e.position, e.refused) for e in events] == [
        (1, None),
        (2, "too_many_properties"),
        (3, None),
    ]
    assert [p.value for p in events[1].props if p.name == "UID"] == ["big@x"]


def test_a_refused_event_is_not_parsed_and_bounded_work_over_a_whole_file():
    """20 MiB of nothing but events over the byte limit: skipped in time, never refused whole."""
    one = corpus.big_event(constants.IMPORT_MAX_EVENT_BYTES + 5_000).decode()
    body = one.split("BEGIN:VEVENT", 1)[1].rsplit("END:VEVENT", 1)[0]
    event = "BEGIN:VEVENT" + body + "END:VEVENT\r\n"
    count = (constants.IMPORT_BODY_CEILING - 1_000) // len(event)
    data = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + event * count + "END:VCALENDAR\r\n").encode()
    assert constants.IMPORT_MAX_EVENTS >= count > 10
    began = time.monotonic()
    scanned = scan(data)
    assert time.monotonic() - began < constants.IMPORT_PARSE_SECONDS
    assert len(scanned.events) == count and all(e.refused for e in scanned.events)
