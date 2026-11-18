"""A per-event limit skips that event with its own code and place; the rest import."""

from __future__ import annotations

from sm_events.core import constants
from sm_events.feeds.importing.mapper import map_calendar
from sm_events.feeds.importing.scan import scan

from tests.feeds.importing import corpus


def _map(data: bytes):
    return map_calendar(scan(data).events, calendar_tz="Europe/Vienna", categories={})


def test_one_oversized_event_is_skipped_and_the_others_import():
    big = corpus.vevent("big@x", *[f"X-P{n}:v" for n in range(600)])
    data = corpus.calendar(*corpus.vevent("a@x"), *big, *corpus.vevent("c@x"))
    items = _map(data).items
    by_uid = {i.uid: i for i in items}
    assert by_uid["a@x"].event is not None and by_uid["c@x"].event is not None
    skipped = by_uid["big@x"]
    assert (skipped.event, skipped.skip) == (None, "too_many_properties")
    assert skipped.title == "#2 Talk"  # its place in the file, and the SUMMARY it had


def test_a_refused_event_without_a_summary_is_named_by_position_alone():
    bare = [x for x in corpus.vevent("b@x", *["X-P:v"] * 600) if not x.startswith("SUMMARY")]
    data = corpus.calendar(*corpus.vevent("a@x"), *bare)
    skipped = next(i for i in _map(data).items if i.skip)
    assert skipped.title == "#2" and skipped.skip == "too_many_properties"


def test_every_per_event_code_is_a_known_refusal():
    codes = set()
    many = ";".join(f"P{n}=v" for n in range(constants.IMPORT_MAX_PARAMS + 1))
    for data in (
        corpus.properties(constants.IMPORT_MAX_PROPERTIES + 1),
        corpus.big_event(constants.IMPORT_MAX_EVENT_BYTES + 5_000),
        corpus.calendar(*corpus.vevent("a@x", f"X-Q;{many}:v")),
        corpus.with_event_lines(constants.IMPORT_MAX_ATTENDEES + 1),
    ):
        codes |= {i.skip for i in _map(data).items}
    assert codes == set(constants.IMPORT_EVENT_REFUSALS)
