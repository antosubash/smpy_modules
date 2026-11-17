"""RRULE allow-list, normalisation, ``recurrence_until`` and bounded iteration."""

from __future__ import annotations

import random
import time
from datetime import UTC, datetime, timedelta

import pytest
from sm_events.calendar import rrule
from sm_events.calendar.times import to_span
from sm_events.core.errors import InvalidRule

VIENNA = "Europe/Vienna"


def parse(text, *, all_day=False, tz=VIENNA):
    return rrule.parse(text, all_day=all_day, timezone=tz)


def span(start="2026-07-01T10:00", end="2026-07-01T11:00", *, all_day=False, tz=VIENNA):
    return to_span(all_day=all_day, timezone=tz, start=start, end=end, recurring=True)


def check(text, *, sp=None, all_day=False, tz=VIENNA):
    sp = sp or span(tz=tz)
    return rrule.validate(parse(text, all_day=all_day, tz=tz), sp, all_day=all_day, timezone=tz)


def code_of(call):
    with pytest.raises(InvalidRule) as caught:
        call()
    return caught.value


def test_normalises():
    assert parse("rrule:byday=we,mo;freq=weekly;interval=1").text == "FREQ=WEEKLY;BYDAY=MO,WE"
    got = parse("FREQ=MONTHLY;BYDAY=-1FR,2MO;INTERVAL=2;WKST=SU;BYMONTH=3,1;BYSETPOS=-1,1")
    assert got.text == ("FREQ=MONTHLY;INTERVAL=2;BYMONTH=1,3;BYDAY=2MO,-1FR;BYSETPOS=-1,1;WKST=SU")
    assert parse("FREQ=MONTHLY;BYMONTHDAY=-1,15,1").text == "FREQ=MONTHLY;BYMONTHDAY=1,15,-1"
    assert parse(parse("FREQ=DAILY;COUNT=5").text).text == "FREQ=DAILY;COUNT=5"


@pytest.mark.parametrize("freq", ["SECONDLY", "MINUTELY", "HOURLY"])
def test_refuses_subdaily(freq):
    assert code_of(lambda: parse(f"FREQ={freq}")).code == "rrule_frequency_refused"


@pytest.mark.parametrize(
    "text",
    [
        "FREQ=DAILY;BYHOUR=3",
        "FREQ=DAILY;BYMINUTE=3",
        "FREQ=DAILY;BYSECOND=3",
        "FREQ=YEARLY;BYWEEKNO=3",
        "FREQ=YEARLY;BYYEARDAY=3",
        "FREQ=DAILY;X-FOO=1",
        "FREQ=DAILY;DTSTART=20260101",
    ],
)
def test_refused_parts(text):
    exc = code_of(lambda: parse(text))
    assert exc.code == "invalid_rrule"
    assert text.split(";")[1].split("=")[0] in exc.detail


@pytest.mark.parametrize(
    "text",
    [
        "FREQ=DAILY;INTERVAL=0",
        "FREQ=DAILY;INTERVAL=100",
        "FREQ=DAILY;COUNT=0",
        "FREQ=DAILY;COUNT=731",
        "FREQ=DAILY;COUNT=3;UNTIL=20270101",
        "FREQ=DAILY;BYSETPOS=1",
        "FREQ=WEEKLY;BYDAY=2MO",
        "FREQ=MONTHLY;BYDAY=6MO",
        "FREQ=MONTHLY;BYDAY=0MO",
        "FREQ=MONTHLY;BYMONTHDAY=0",
        "FREQ=MONTHLY;BYMONTHDAY=32",
        "FREQ=YEARLY;BYMONTH=13",
        "FREQ=DAILY;WKST=XX",
        "FREQ=FORTNIGHTLY",
        "INTERVAL=2",
        "",
        "FREQ=DAILY;FREQ=WEEKLY",
        "FREQ=DAILY;;",
        "FREQ=DAILY;UNTIL=tomorrow",
        "FREQ=DAILY;INTERVAL=-1",
        "FREQ=DAILY;" + "BYMONTH=1;" * 100,
    ],
)
def test_bounds_at_parse(text):
    assert code_of(lambda: parse(text)).code == "invalid_rrule"


def test_length_bound():
    assert (
        code_of(lambda: parse("FREQ=WEEKLY;BYDAY=" + ",".join(["MO"] * 200))).code
        == "invalid_rrule"
    )


def test_until_bounds_at_validate():
    assert code_of(lambda: check("FREQ=DAILY;UNTIL=20260601T000000Z")).code == "invalid_rrule"
    assert code_of(lambda: check("FREQ=DAILY;UNTIL=21260702T000000Z")).code == "invalid_rrule"
    assert check("FREQ=DAILY;UNTIL=20260701T080000Z") is not None  # the start itself


def test_start_not_in_rule():
    sp = span("2026-06-30T10:00", "2026-06-30T11:00")  # a Tuesday
    assert code_of(lambda: check("FREQ=WEEKLY;BYDAY=MO", sp=sp)).code == "start_not_in_rule"
    assert check("FREQ=WEEKLY;BYDAY=TU", sp=sp) is None


def test_until_derivation():
    assert check("FREQ=DAILY;COUNT=3") == datetime(2026, 7, 3, 9, tzinfo=UTC)
    assert check("FREQ=DAILY;UNTIL=20260705T235959Z") == datetime(2026, 7, 5, 9, tzinfo=UTC)
    assert check("FREQ=DAILY") is None
    got = check(
        "FREQ=DAILY;UNTIL=20260705", all_day=True, sp=span("2026-07-01", "2026-07-01", all_day=True)
    )
    # all-day: the exclusive local midnight after 5 July (Vienna is UTC+2)
    assert got == datetime(2026, 7, 5, 22, tzinfo=UTC)
    assert parse("FREQ=DAILY;UNTIL=20260705", all_day=True).text == "FREQ=DAILY;UNTIL=20260705"


def test_all_day_multi_day_instance_end():
    sp = span("2026-07-01", "2026-07-02", all_day=True)
    got = check("FREQ=WEEKLY;COUNT=2", all_day=True, sp=sp)
    assert got == datetime(2026, 7, 9, 22, tzinfo=UTC)  # 8 July + 2 days, local midnight


def test_timed_until_as_date():
    rule = parse("FREQ=DAILY;UNTIL=20260705")
    assert rule.until == datetime(2026, 7, 5, 21, 59, 59, tzinfo=UTC)
    assert rule.text == "FREQ=DAILY;UNTIL=20260705T215959Z"
    assert check("FREQ=DAILY;UNTIL=20260705") == datetime(2026, 7, 5, 9, tzinfo=UTC)


def test_count_beyond_the_horizon_is_refused():
    # 200 yearly instances do not fit in 100 years
    assert code_of(lambda: check("FREQ=YEARLY;COUNT=200")).code == "invalid_rrule"
    assert check("FREQ=YEARLY;COUNT=100") is not None


def test_impossible_rule_terminates():
    sp = span("2026-02-28T10:00", "2026-02-28T11:00")
    for text in (
        "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30",
        "FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30",
        "FREQ=WEEKLY;BYMONTH=2;BYMONTHDAY=31",
        "FREQ=MONTHLY;BYMONTH=4;BYMONTHDAY=31",
    ):
        began = time.monotonic()
        assert code_of(lambda text=text: check(text, sp=sp)).code == "start_not_in_rule"
        assert time.monotonic() - began < 1.0, text


def test_month_end_and_leap_rules():
    sp = span("2026-01-31T10:00", "2026-01-31T11:00", tz="UTC")
    rule = parse("FREQ=MONTHLY;BYMONTHDAY=31", tz="UTC")
    got = list(
        rrule.iterate(
            rule,
            dtstart_local=datetime(2026, 1, 31, 10),
            lower_local=datetime(2026, 1, 31),
            until_local=datetime(2026, 12, 31, 23),
        )
    )
    assert [d.month for d in got] == [1, 3, 5, 7, 8, 10, 12]
    assert rrule.validate(rule, sp, all_day=False, timezone="UTC") is None
    leap = parse("FREQ=YEARLY", tz="UTC")
    feb29 = to_span(
        all_day=False,
        timezone="UTC",
        start="2028-02-29T10:00",
        end="2028-02-29T11:00",
        recurring=True,
    )
    years = [
        d.year
        for d in rrule.iterate(
            leap,
            dtstart_local=datetime(2028, 2, 29, 10),
            lower_local=datetime(2028, 1, 1),
            until_local=datetime(2041, 1, 1),
        )
    ]
    assert years == [2028, 2032, 2036, 2040]
    assert rrule.validate(leap, feb29, all_day=False, timezone="UTC") is None


def test_build_requires_until():
    rule = parse("FREQ=DAILY")
    with pytest.raises(ValueError):
        rrule.build(rule, dtstart_local=datetime(2026, 7, 1, 10), until_local=None)


RULES = [
    "FREQ=DAILY",
    "FREQ=DAILY;INTERVAL=3",
    "FREQ=WEEKLY",
    "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH",
    "FREQ=WEEKLY;INTERVAL=3;BYDAY=SU,MO;WKST=SU",
    "FREQ=MONTHLY",
    "FREQ=MONTHLY;INTERVAL=5",
    "FREQ=MONTHLY;BYMONTHDAY=31",
    "FREQ=MONTHLY;BYMONTHDAY=-1",
    "FREQ=MONTHLY;BYDAY=2TU",
    "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
    "FREQ=YEARLY",
    "FREQ=YEARLY;INTERVAL=2;BYMONTH=2,8;BYMONTHDAY=29",
    "FREQ=YEARLY;BYDAY=-1FR;BYMONTH=10",
]


def test_property_skip_ahead_equals_full_walk():
    """``iterate`` (period-aligned start, 400-year shift) is dateutil's full walk."""
    rng = random.Random(3)
    for _ in range(300):
        text = rng.choice(RULES)
        rule = parse(text, tz="UTC")
        start = datetime(2020, 1, 1, rng.randrange(24), rng.choice([0, 30])) + timedelta(
            days=rng.randrange(0, 2000)
        )
        lower = start + timedelta(days=rng.randrange(0, 1500), hours=rng.randrange(24))
        until = lower + timedelta(days=rng.randrange(1, 800))
        full = [d for d in build_walk(rule, start, until) if d >= lower]
        got = list(rrule.iterate(rule, dtstart_local=start, lower_local=lower, until_local=until))
        assert got == full, (text, start, lower, until)


def build_walk(rule, start, until):
    return list(rrule.build(rule, dtstart_local=start, until_local=until))


def test_iteration_is_cheap_for_an_old_series():
    rule = parse("FREQ=DAILY", tz="UTC")
    began = time.monotonic()
    got = list(
        rrule.iterate(
            rule,
            dtstart_local=datetime(1990, 1, 1, 10),
            lower_local=datetime(2026, 7, 1),
            until_local=datetime(2026, 7, 31),
        )
    )
    assert len(got) == 30  # 1-30 July at 10:00; 31 July 10:00 is past the bound
    assert time.monotonic() - began < 0.05
