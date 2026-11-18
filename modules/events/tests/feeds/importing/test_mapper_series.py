"""A series: its rule, the start the module requires, skipped, cancelled and moved occurrences."""

from __future__ import annotations

from datetime import UTC, datetime

from sm_events.core import constants

from tests.feeds.importing.mapping import event, mapped, one

VIENNA = "TZID=Europe/Vienna"


def weekly(uid="s@x", *extra: str, count=8):
    """Mondays 10:00 Vienna from 2026-07-06."""
    return event(
        uid,
        f"RRULE:FREQ=WEEKLY;COUNT={count}",
        *extra,
        start="20260706T100000",
        end="20260706T110000",
    )


def series(*extra: str, count=8):
    lines = weekly("s@x", *extra, count=count)
    lines[2] = f"DTSTART;{VIENNA}:20260706T100000"
    lines[3] = f"DTEND;{VIENNA}:20260706T110000"
    return lines


def child(recurrence: str, *extra: str, start: str, end: str):
    return [
        "BEGIN:VEVENT",
        "UID:s@x",
        f"RECURRENCE-ID;{VIENNA}:{recurrence}",
        f"DTSTART;{VIENNA}:{start}",
        f"DTEND;{VIENNA}:{end}",
        *extra,
        "END:VEVENT",
    ]


def utc(day: int, hour: int = 8) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=UTC)


def test_exdate_to_skipped():
    item = one(*series(f"EXDATE;{VIENNA}:20260713T100000,20260720T100000"))
    assert item.event is not None
    got = [(o.original_start, o.kind) for o in item.event.overrides]
    assert got == [(utc(13), "skipped"), (utc(20), "skipped")]


def test_exdate_not_an_occurrence_ignored():
    item = one(*series(f"EXDATE;{VIENNA}:20260714T100000"))  # a Tuesday
    assert item.event and item.event.overrides == [] and "exdate_ignored" in item.notes


def test_recurrence_id_moved_and_cancelled():
    got = mapped(
        *series(),
        *child("20260713T100000", start="20260714T150000", end="20260714T160000"),
        *child(
            "20260720T100000", "STATUS:CANCELLED", start="20260720T100000", end="20260720T110000"
        ),
    )
    assert len(got.items) == 1
    overrides = got.items[0].event.overrides  # type: ignore[union-attr]
    by_start = {o.original_start: o for o in overrides}
    moved, cancelled = by_start[utc(13)], by_start[utc(20)]
    assert (moved.kind, moved.start, moved.end) == ("moved", "2026-07-14T15:00", "2026-07-14T16:00")
    assert (cancelled.kind, cancelled.start, cancelled.end) == ("cancelled", None, None)


def test_a_child_beats_an_exdate_for_the_same_occurrence():
    got = mapped(
        *series(f"EXDATE;{VIENNA}:20260713T100000"),
        *child("20260713T100000", start="20260713T120000", end="20260713T130000"),
    )
    (override,) = got.items[0].event.overrides  # type: ignore[union-attr]
    assert override.kind == "moved"


def test_override_fields_dropped_noted():
    got = mapped(
        *series(),
        *child(
            "20260713T100000",
            "SUMMARY:Different",
            "LOCATION:Elsewhere",
            start="20260713T110000",
            end="20260713T120000",
        ),
    )
    assert "override_fields_dropped" in got.items[0].notes


def test_thisandfuture_dropped():
    lines = child("20260713T100000", start="20260713T110000", end="20260713T120000")
    lines[2] = f"RECURRENCE-ID;{VIENNA};RANGE=THISANDFUTURE:20260713T100000"
    got = mapped(*series(), *lines)
    assert got.items[0].event.overrides == [] and "override_dropped" in got.items[0].notes  # type: ignore[union-attr]


def test_children_that_do_not_fit_are_dropped_and_noted():
    got = mapped(
        *series(),
        *child(
            "20260714T100000", start="20260714T110000", end="20260714T120000"
        ),  # not an occurrence
        *child("20260713T100000", start="20260713T110000", end="20260901T120000"),  # too long
    )
    assert got.items[0].event.overrides == [] and "override_dropped" in got.items[0].notes  # type: ignore[union-attr]


def test_an_all_day_child_of_a_timed_series_is_dropped():
    lines = child("20260713T100000", start="20260713", end="20260714")
    lines[3] = "DTSTART;VALUE=DATE:20260713"
    lines[4] = "DTEND;VALUE=DATE:20260714"
    got = mapped(*series(), *lines)
    assert got.items[0].event.overrides == []  # type: ignore[union-attr]


def test_override_without_master():
    got = mapped(*child("20260713T100000", start="20260713T110000", end="20260713T120000"))
    assert [i.skip for i in got.items] == ["override_without_master"]
    assert got.items[0].event is None


def test_children_of_a_one_off_are_orphans():
    got = mapped(
        *event("s@x"), *child("20260701T100000", start="20260701T110000", end="20260701T120000")
    )
    assert [i.skip for i in got.items] == [None, "override_without_master"]


def test_too_many_overrides():
    n = constants.IMPORT_MAX_OVERRIDES + 1
    children = [
        line
        for i in range(n)
        for line in child(
            f"2026{i % 12 + 1:02d}{i % 28 + 1:02d}T100000",
            start="20260713T110000",
            end="20260713T120000",
        )
    ]
    got = mapped(*series(count=730), *children)
    assert got.items[0].skip == "too_many_overrides" and got.items[0].event is None


def test_too_many_exdates():
    dates = ",".join(
        f"20260{i % 9 + 1}{i % 28 + 1:02d}T100000" for i in range(constants.IMPORT_MAX_EXDATES + 1)
    )
    item = one(*series(f"EXDATE;{VIENNA}:{dates}"))
    assert item.skip == "too_many_overrides"


def test_start_adjusted():
    # A Tuesday start with a Monday rule: RFC 5545 counts the stray start as one instance.
    lines = event(
        "s@x",
        "RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=5",
        start="20260707T100000Z",
        end="20260707T110000Z",
    )
    item = one(*lines)
    e = item.event
    assert e is not None and "start_adjusted" in item.notes
    assert e.times.start == "2026-07-13T10:00" and e.times.end == "2026-07-13T11:00"
    assert e.rrule == "FREQ=WEEKLY;COUNT=4;BYDAY=MO"


def test_start_adjusted_count_one_is_a_one_off():
    lines = event(
        "s@x",
        "RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=1",
        start="20260707T100000Z",
        end="20260707T110000Z",
    )
    item = one(*lines)
    assert item.event and item.event.rrule is None and not item.recurring
    assert item.event.times.start == "2026-07-13T10:00" and "start_adjusted" in item.notes


def test_start_adjusted_with_no_later_instance_is_refused():
    lines = event(
        "s@x",
        "RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20260707T120000Z",
        start="20260707T100000Z",
        end="20260707T110000Z",
    )
    assert one(*lines).skip == "unsupported_rule"


def test_all_day_series_values_are_dates():
    lines = [
        "BEGIN:VEVENT",
        "UID:d@x",
        "DTSTART;VALUE=DATE:20260706",
        "DTEND;VALUE=DATE:20260707",
        "RRULE:FREQ=WEEKLY;COUNT=3",
        "EXDATE;VALUE=DATE:20260713",
        "SUMMARY:Day",
        "END:VEVENT",
    ]
    item = one(*lines)
    e = item.event
    assert e and e.times.all_day and (e.times.start, e.times.end) == ("2026-07-06", "2026-07-06")
    (override,) = e.overrides
    assert override.kind == "skipped" and override.original_start == datetime(
        2026, 7, 12, 22, tzinfo=UTC
    )


def test_a_date_valued_until_on_a_timed_rule_is_the_end_of_that_local_day():
    """``UNTIL=20260727`` keeps the Monday 27 July 10:00 occurrence (the day's end)."""
    from sm_events.calendar import rrule
    from sm_events.calendar.expand import instances
    from sm_events.calendar.times import to_span

    lines = event(
        "u@x",
        "RRULE:FREQ=WEEKLY;UNTIL=20260727",
        dtstart=f"DTSTART;{VIENNA}:20260706T100000",
        start="20260706T100000",
        end="20260706T110000",
    )
    lines[3] = f"DTEND;{VIENNA}:20260706T110000"
    e = one(*lines).event
    assert e is not None
    span = to_span(
        all_day=False,
        timezone=e.times.timezone,
        start=e.times.start,
        end=e.times.end,
        recurring=True,
    )
    rule = rrule.parse(e.rrule, all_day=False, timezone=e.times.timezone)
    until = rrule.validate(rule, span, all_day=False, timezone=e.times.timezone)
    days = [
        i.start.astimezone(__import__("zoneinfo").ZoneInfo(e.times.timezone)).day
        for i in instances(
            rule=rule,
            span=span,
            all_day=False,
            timezone=e.times.timezone,
            window_start=span.starts_at,
            window_end=span.starts_at.replace(year=2027),
            recurrence_until=until,
        )
    ]
    assert days == [6, 13, 20, 27]
