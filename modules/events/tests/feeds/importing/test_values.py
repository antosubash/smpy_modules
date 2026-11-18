"""Reading dates, times and zones from a file's own text: never a library, never a file's zone."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.feeds.importing.scan import Prop
from sm_events.feeds.importing.values import ItemSkip, read_instants, read_when, resolve_tzid

VIENNA = "Europe/Vienna"


def P(name: str, text: str, **params: str) -> Prop:  # noqa: N802 - reads like the file
    return Prop(name.upper(), {k.upper().replace("_", "-"): v for k, v in params.items()}, text)


def when(*props: Prop, tz: str = VIENNA, into: str | None = None):
    return read_when(list(props), calendar_tz=tz, into=into)


def skip_code(*props: Prop) -> str:
    with pytest.raises(ItemSkip) as caught:
        when(*props)
    return caught.value.code


def test_tzid_vienna():
    got = when(
        P("DTSTART", "20260316T100000", tzid=VIENNA), P("DTEND", "20260316T113000", tzid=VIENNA)
    )
    assert (got.all_day, got.timezone, got.start, got.end) == (
        False,
        VIENNA,
        "2026-03-16T10:00",
        "2026-03-16T11:30",
    )
    assert got.notes == ()


@pytest.mark.parametrize(
    "name", ["W. Europe Standard Time", "tzone://Microsoft/W. Europe Standard Time"]
)
def test_windows_and_tzone(name):
    zone = resolve_tzid(name)
    assert zone is not None and zone in ("Europe/Berlin", "Europe/Vienna")
    got = when(P("DTSTART", "20260316T100000", tzid=name), P("DTEND", "20260316T110000", tzid=name))
    assert got.timezone == zone


@pytest.mark.parametrize(
    "tzid",
    ["My Custom Zone", "", "../../etc/passwd", "Europe/Nowhere", "x" * 500, "UTC+1", "Etc/\x00UTC"],
)
def test_unknown_tzid_skips(tzid, monkeypatch):
    """A file's own zone definition is never trusted or evaluated: the item is skipped."""
    import icalendar

    def refuse(*_a, **_k):
        raise AssertionError("a VTIMEZONE must never be evaluated")

    monkeypatch.setattr(icalendar.Timezone, "to_tz", refuse, raising=False)
    assert resolve_tzid(tzid) is None
    assert skip_code(P("DTSTART", "20260316T100000", tzid=tzid)) == "unknown_timezone"


def test_iana_names_only_from_the_database():
    assert resolve_tzid("UTC") == "UTC"
    assert resolve_tzid("America/New_York") == "America/New_York"
    assert resolve_tzid(None) is None


def test_utc_goes_to_calendar_zone():
    got = when(P("DTSTART", "20260701T080000Z"), P("DTEND", "20260701T093000Z"))
    assert (got.timezone, got.start, got.end) == (VIENNA, "2026-07-01T10:00", "2026-07-01T11:30")
    assert got.notes == ()


def test_floating_noted():
    got = when(P("DTSTART", "20260701T100000"), P("DTEND", "20260701T110000"))
    assert (got.timezone, got.start) == (VIENNA, "2026-07-01T10:00")
    assert "floating_time" in got.notes


def test_all_day_exclusive_end():
    got = when(P("DTSTART", "20260329", value="DATE"), P("DTEND", "20260331", value="DATE"))
    assert (got.all_day, got.start, got.end, got.timezone) == (
        True,
        "2026-03-29",
        "2026-03-30",
        VIENNA,
    )
    bare = when(P("DTSTART", "20260329"), P("DTEND", "20260331"))  # 8 digits is a date too
    assert bare.all_day and bare.end == "2026-03-30"


@pytest.mark.parametrize(
    ("duration", "end"),
    [
        ("PT90M", "2026-07-01T13:30"),
        ("PT1H30M", "2026-07-01T13:30"),
        ("P1DT1H", "2026-07-02T13:00"),
    ],
)
def test_duration(duration, end):
    got = when(P("DTSTART", "20260701T100000Z"), P("DURATION", duration))
    assert (got.start, got.end) == ("2026-07-01T12:00", end)


def test_duration_on_dates():
    got = when(P("DTSTART", "20260701", value="DATE"), P("DURATION", "P2D"))
    assert (got.start, got.end) == ("2026-07-01", "2026-07-02")
    week = when(P("DTSTART", "20260701", value="DATE"), P("DURATION", "P1W"))
    assert week.end == "2026-07-07"
    assert (
        skip_code(P("DTSTART", "20260701", value="DATE"), P("DURATION", "PT1H")) == "invalid_times"
    )


@pytest.mark.parametrize(
    "duration", ["-PT1H", "PT0S", "P", "PT", "1H", "P1X", "PT1H" * 50, "P999999999D"]
)
def test_bad_durations_skip(duration):
    assert skip_code(P("DTSTART", "20260701T100000Z"), P("DURATION", duration)) == "invalid_times"


def test_no_end():
    one_day = when(P("DTSTART", "20260701", value="DATE"))
    assert (one_day.start, one_day.end, one_day.notes) == ("2026-07-01", "2026-07-01", ())
    timed = when(P("DTSTART", "20260701T100000", tzid=VIENNA))
    assert (timed.start, timed.end) == ("2026-07-01T10:00", "2026-07-01T11:00")
    assert "default_duration" in timed.notes


def test_mixed_kinds_skip():
    assert (
        skip_code(P("DTSTART", "20260701", value="DATE"), P("DTEND", "20260701T100000Z"))
        == "invalid_times"
    )
    assert (
        skip_code(P("DTSTART", "20260701T100000Z"), P("DTEND", "20260702", value="DATE"))
        == "invalid_times"
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("20260329T023000", "20260329T043000"),  # the start is in the gap, the end is valid
        ("20260329T013000", "20260329T023000"),  # the start is valid, the end is in the gap
        ("20270328T023000", "20270328T033000"),  # both in the gap (QA: was end_before_start)
        ("20260329T023000", "20260329T024500"),  # both, still ordered
    ],
)
def test_a_wall_time_the_clocks_skip_is_the_modules_own_invalid_local_time(start, end):
    assert (
        skip_code(P("DTSTART", start, tzid=VIENNA), P("DTEND", end, tzid=VIENNA))
        == "invalid_local_time"
    )


def test_a_time_just_outside_the_gap_is_fine():
    got = when(
        P("DTSTART", "20260329T030000", tzid=VIENNA), P("DTEND", "20260329T040000", tzid=VIENNA)
    )
    assert (got.start, got.end) == ("2026-03-29T03:00", "2026-03-29T04:00")


def test_the_repeated_hour_is_its_first_occurrence_not_a_skip():
    got = when(
        P("DTSTART", "20261025T023000", tzid=VIENNA), P("DTEND", "20261025T033000", tzid=VIENNA)
    )
    assert (got.start, got.end) == ("2026-10-25T02:30", "2026-10-25T03:30")


def test_fold_takes_the_first_occurrence():
    got = when(
        P("DTSTART", "20261025T023000", tzid=VIENNA), P("DTEND", "20261025T033000", tzid=VIENNA)
    )
    assert got.start == "2026-10-25T02:30" and got.notes == ()


def test_end_in_another_zone_is_converted():
    got = when(P("DTSTART", "20260701T100000", tzid=VIENNA), P("DTEND", "20260701T090000Z"))
    assert (got.start, got.end) == ("2026-07-01T10:00", "2026-07-01T11:00")


def test_into_a_given_zone():
    got = when(
        P("DTSTART", "20260701T080000Z"), P("DTEND", "20260701T090000Z"), tz="UTC", into=VIENNA
    )
    assert (got.timezone, got.start, got.end) == (VIENNA, "2026-07-01T10:00", "2026-07-01T11:00")


GARBAGE = [
    "",
    "2026-07-01",
    "20261301T100000",
    "20260230",
    "20260701T250000",
    "abc",
    "20260701T100000ZZ",
    "00010101T000000Z",
    "99999999T000000",
    "2026070",
    "20260701T1000",
    " " * 10,
    "\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18",  # full-width digits
]


@pytest.mark.parametrize("value", GARBAGE)
def test_garbage_values_skip(value):
    assert skip_code(P("DTSTART", value)) == "invalid_times"


def test_missing_start_skips():
    assert skip_code(P("DTEND", "20260701T100000Z")) == "invalid_times"
    assert skip_code() == "invalid_times"


def test_instant_list():
    got = read_instants(
        P("EXDATE", "20260706T080000Z,20260713T080000Z,20260720T080000Z"), tz=VIENNA, all_day=False
    )
    assert got == [datetime(2026, 7, d, 8, tzinfo=UTC) for d in (6, 13, 20)]


def test_instants_with_a_zone_dates_and_floating():
    tzid = read_instants(P("EXDATE", "20260706T100000", tzid=VIENNA), tz="UTC", all_day=False)
    assert tzid == [datetime(2026, 7, 6, 8, tzinfo=UTC)]
    floating = read_instants(P("EXDATE", "20260706T100000"), tz=VIENNA, all_day=False)
    assert floating == [datetime(2026, 7, 6, 8, tzinfo=UTC)]
    days = read_instants(P("EXDATE", "20260706,20260707", value="DATE"), tz=VIENNA, all_day=True)
    assert days == [datetime(2026, 7, 5, 22, tzinfo=UTC), datetime(2026, 7, 6, 22, tzinfo=UTC)]


def test_instants_of_the_wrong_kind_skip():
    with pytest.raises(ItemSkip):
        read_instants(P("EXDATE", "20260706", value="DATE"), tz=VIENNA, all_day=False)
    with pytest.raises(ItemSkip):
        read_instants(P("EXDATE", "20260706T100000Z"), tz=VIENNA, all_day=True)
    with pytest.raises(ItemSkip):
        read_instants(P("EXDATE", "junk,20260706T100000Z"), tz=VIENNA, all_day=False)
