"""VEVENT groups mapped onto what the module's own validators accept."""

from __future__ import annotations

import time

import pytest
from sm_events.core import constants

from tests.feeds.importing import corpus
from tests.feeds.importing.mapping import CAT, event, mapped, one


def test_fields():
    item = one(
        *event(
            "a@x",
            "DESCRIPTION:Line one\\nLine two",
            "LOCATION:Room 4\\, Hall",
            "GEO:48.2;16.37",
            "STATUS:CANCELLED",
            "URL:https://example.org/talk",
            summary="Real talk",
        )
    )
    e = item.event
    assert e is not None and item.skip is None
    assert (e.uid, e.title, e.venue_name, e.cancelled) == ("a@x", "Real talk", "Room 4, Hall", True)
    assert (e.latitude, e.longitude, e.attendance_mode) == (48.2, 16.37, "in_person")
    assert (
        "<p>Line one<br>Line two</p>" in e.description
        and 'href="https://example.org/talk"' in e.description
    )
    assert (e.times.timezone, e.times.start, e.times.end) == (
        "Europe/Vienna",
        "2026-07-01T12:00",
        "2026-07-01T13:00",
    )
    assert e.rrule is None and e.overrides == [] and e.private_class is False


def test_online_location_and_bad_geo():
    online = one(*event("a@x", "LOCATION:https://meet.example.org/x")).event
    assert (
        online
        and online.online_url == "https://meet.example.org/x"
        and online.attendance_mode == "online"
    )
    assert online.venue_name is None
    for geo in ("91;10", "10;181", "x;y", "10", "nan;1", "1;inf", "10;20;30"):
        e = one(*event("a@x", f"GEO:{geo}")).event
        assert e and (e.latitude, e.longitude) == (None, None), geo
    assert one(*event("a@x", "LOCATION:javascript:alert(1)")).event.online_url is None  # type: ignore[union-attr]


def test_categories_matched_case_insensitively_never_created():
    cats = {"talks": CAT}
    hit = one(*event("a@x", "CATEGORIES:Other,TALKS"), categories=cats)
    assert hit.event and hit.event.category_id == CAT and "category_dropped" not in hit.notes
    miss = one(*event("a@x", "CATEGORIES:Nothing,Else"), categories=cats)
    assert miss.event and miss.event.category_id is None and "category_dropped" in miss.notes
    none = one(*event("a@x"), categories=cats)
    assert none.event and "category_dropped" not in none.notes


@pytest.mark.parametrize("klass", ["PRIVATE", "CONFIDENTIAL", "private"])
def test_class_private_kept_draft(klass):
    item = one(*event("a@x", f"CLASS:{klass}"))
    assert item.event and item.event.private_class and "kept_draft_private" in item.notes
    public = one(*event("a@x", "CLASS:PUBLIC"))
    assert public.event and not public.event.private_class


def test_dropped_counted_by_name_and_never_stored():
    got = mapped(
        *event(
            "a@x",
            "ATTENDEE;CN=Jane Doe:mailto:jane@example.com",
            "ATTENDEE:mailto:b@example.com",
            "ATTENDEE:mailto:c@example.com",
            "ORGANIZER;CN=Boss:mailto:boss@example.com",
            "ATTACH:http://127.0.0.1/secret",
            "RELATED-TO:other",
            "X-ALT-DESC;FMTTYPE=text/html:<b>x</b>",
            "X-FOO:1",
            "X-BAR:2",
            "TRANSP:OPAQUE",
            "BEGIN:VALARM",
            "ACTION:AUDIO",
            "END:VALARM",
        )
    )
    assert dict(got.dropped) == {
        "ATTENDEE": 3,
        "ORGANIZER": 1,
        "ATTACH": 1,
        "RELATED-TO": 1,
        "X-ALT-DESC": 1,
        "X-*": 2,
        "VALARM": 1,
    }
    blob = repr(got.items[0])
    for private in ("jane@example.com", "Jane", "boss@example.com", "127.0.0.1", "secret"):
        assert private not in blob


def test_other_unknown_properties_are_one_bucket():
    got = mapped(*event("a@x", "PRIORITY:1", "COMMENT:hello", "GEOZ:1"))
    assert got.dropped["other"] == 3


def test_uid_rules():
    assert one(*event("Verbatim_UID-1@Host")).event.uid == "Verbatim_UID-1@Host"  # type: ignore[union-attr]
    too_long = one(*event("u" * 256))
    assert too_long.skip == "uid_too_long" and too_long.event is None
    assert one(*event("u" * 255)).skip is None
    bad = one(*event("a\x07b"))
    assert bad.skip == "uid_invalid"
    first = one(
        "BEGIN:VEVENT",
        "DTSTART:20260701T100000Z",
        "DTEND:20260701T110000Z",
        "SUMMARY:T",
        "END:VEVENT",
    )
    again = one(
        "BEGIN:VEVENT",
        "DTSTART:20260701T100000Z",
        "DTEND:20260701T110000Z",
        "SUMMARY:T",
        "END:VEVENT",
    )
    assert first.event and first.event.uid == again.event.uid  # type: ignore[union-attr]
    assert (
        first.event.uid.endswith("@import" + constants.UID_SUFFIX)
        and "uid_generated" in first.notes
    )
    other = one(
        "BEGIN:VEVENT",
        "DTSTART:20260702T100000Z",
        "DTEND:20260702T110000Z",
        "SUMMARY:T",
        "END:VEVENT",
    )
    assert other.event and other.event.uid != first.event.uid  # type: ignore[union-attr]


def test_duplicate_masters_higher_sequence_wins():
    got = mapped(
        *event("d@x", "SEQUENCE:1", summary="old"),
        *event("d@x", "SEQUENCE:3", summary="newest"),
        *event("d@x", "SEQUENCE:2", summary="middle"),
    )
    by_skip = {i.skip: i for i in got.items}
    assert by_skip[None].event.title == "newest"  # type: ignore[union-attr]
    assert [i.skip for i in got.items].count("duplicate_uid") == 2
    tie = mapped(*event("t@x", summary="first"), *event("t@x", summary="second"))
    winner = next(i for i in tie.items if i.skip is None)
    assert winner.event.title == "second"  # type: ignore[union-attr]


def test_a_skipped_item_still_names_itself_without_private_data():
    item = one(*event("a@x", summary="Visible title", dtstart="DTSTART:garbage"))
    assert item.skip == "invalid_times" and item.event is None
    assert item.title == "Visible title" and item.uid == "a@x"


def test_time_errors_become_reasons():
    assert (
        one(*event("a@x", start="20260701T120000Z", end="20260701T100000Z")).skip
        == "end_before_start"
    )
    assert (
        one(*event("a@x", start="20260101T100000Z", end="20270301T100000Z")).skip
        == "duration_too_long"
    )
    assert (
        one(*event("a@x", dtstart="DTSTART;TZID=Nowhere/Zone:20260701T100000")).skip
        == "unknown_timezone"
    )


HOSTILE_RULES = [
    ["RRULE:FREQ=SECONDLY"],
    ["RRULE:FREQ=MINUTELY;INTERVAL=1"],
    ["RRULE:FREQ=HOURLY"],
    ["RRULE:FREQ=DAILY;BYHOUR=1"],
    ["RRULE:FREQ=DAILY;COUNT=731"],
    ["RRULE:FREQ=DAILY;INTERVAL=100"],
    ["RRULE:FREQ=DAILY", "RRULE:FREQ=WEEKLY"],
    ["RRULE:FREQ=DAILY", "RDATE:20260801T100000Z"],
    ["RRULE:FREQ=DAILY", "EXRULE:FREQ=WEEKLY"],
    ["RDATE:20260801T100000Z,20260901T100000Z"],
    ["RRULE:FREQ=DAILY;UNTIL=21300101T000000Z"],
    ["RRULE:FREQ=DAILY;UNTIL=20260701T090000Z"],
    ["RRULE:" + "FREQ=DAILY;" * 80],
    ["RRULE:FREQ=ÜAILY"],
    ["RRULE:FREQ=WEEKLY;BYDAY=" + ",".join(["MO"] * 400)],
    ["RRULE:FREQ=MONTHLY;BYMONTHDAY=31;BYSETPOS=9999"],
]


@pytest.mark.parametrize("rule", HOSTILE_RULES, ids=[r[0][:40] for r in HOSTILE_RULES])
def test_mapper_hostile_rules(rule):
    began = time.monotonic()
    item = one(*event("a@x", *rule))
    assert time.monotonic() - began < 1.0
    assert item.skip == "unsupported_rule" and item.event is None


def test_a_good_rule_passes_unchanged():
    item = one(*event("a@x", "RRULE:FREQ=WEEKLY;COUNT=4"))
    assert item.event and item.event.rrule == "FREQ=WEEKLY;COUNT=4" and item.recurring
    assert item.starts_at is not None


def test_text_from_the_file_cannot_carry_markup_or_controls_into_the_event():
    item = one(
        *event(
            "a@x",
            "DESCRIPTION:<script>x</script>",
            "LOCATION:<i>Room</i>",
            summary="<b>Hi</b>\u202e\x07",
        )
    )
    e = item.event
    assert e and "\x07" not in e.title and "\u202e" not in e.title
    assert "<script" not in e.description
    assert e.venue_name == "<i>Room</i>"  # a plain-text field: escaped where it is shown


def test_many_events_map_in_bounded_time():
    began = time.monotonic()
    got = mapped(*[line for n in range(1500) for line in event(f"u{n}@x")])
    assert len(got.items) == 1500 and time.monotonic() - began < 5


def test_corpus_helper_is_used():
    assert corpus.simple()


def test_an_outlook_all_day_event_is_all_day():
    """Outlook writes TZID midnight-to-midnight times and a flag; it means a whole day."""
    lines = event(
        "o@x",
        "X-MICROSOFT-CDO-ALLDAYEVENT:TRUE",
        dtstart="DTSTART;TZID=Europe/Vienna:20260706T000000",
    )
    lines[3] = "DTEND;TZID=Europe/Vienna:20260708T000000"
    e = one(*lines).event
    assert e is not None and e.times.all_day
    assert (e.times.start, e.times.end) == ("2026-07-06", "2026-07-07")


def test_the_flag_alone_does_not_make_an_event_all_day():
    lines = event(
        "o@x",
        "X-MICROSOFT-CDO-ALLDAYEVENT:TRUE",
        dtstart="DTSTART;TZID=Europe/Vienna:20260706T090000",
    )
    lines[3] = "DTEND;TZID=Europe/Vienna:20260706T100000"
    assert not one(*lines).event.times.all_day  # type: ignore[union-attr]
    false = event(
        "o@x",
        "X-MICROSOFT-CDO-ALLDAYEVENT:FALSE",
        dtstart="DTSTART;TZID=Europe/Vienna:20260706T000000",
    )
    false[3] = "DTEND;TZID=Europe/Vienna:20260707T000000"
    assert not one(*false).event.times.all_day  # type: ignore[union-attr]
