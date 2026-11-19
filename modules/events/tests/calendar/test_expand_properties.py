"""Expansion properties: wall clock, bounds and round trips against ``is_occurrence``."""

from __future__ import annotations

import random
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sm_events.calendar import rrule
from sm_events.calendar.expand import instances, is_occurrence
from sm_events.calendar.times import is_nonexistent, to_span
from sm_events.core.errors import InvalidRule

from tests.support.occurrences import utc

VIENNA = "Europe/Vienna"

ZONES = ["Europe/Vienna", "America/New_York", "Australia/Sydney", "Australia/Lord_Howe", "UTC"]
RULES = [
    "FREQ=DAILY;INTERVAL=2",
    "FREQ=WEEKLY;BYDAY=MO,WE,FR",
    "FREQ=WEEKLY;INTERVAL=2",
    "FREQ=MONTHLY",
    "FREQ=MONTHLY;BYDAY=2TU",
    "FREQ=MONTHLY;BYMONTHDAY=-1",
    "FREQ=YEARLY",
]


def test_property_wall_clock():
    rng = random.Random(5)
    checked = skipped = 0
    for _ in range(300):
        name = rng.choice(ZONES)
        tz = ZoneInfo(name)
        text = rng.choice(RULES)
        day = datetime(2026, 1, 1) + timedelta(days=rng.randrange(0, 200))
        start_local = day.replace(hour=rng.randrange(24), minute=rng.choice([0, 15, 30, 45]))
        if rrule_is_gap(start_local, tz):
            continue
        sp = (
            to_span(
                all_day=False,
                timezone=name,
                start=start_local.isoformat(timespec="minutes"),
                end=(start_local + timedelta(hours=1)).isoformat(timespec="minutes"),
                recurring=True,
            )
            if not rrule_is_gap(start_local + timedelta(hours=1), tz)
            else None
        )
        if sp is None:
            continue
        rule = rrule.parse(text, all_day=False, timezone=name)
        try:
            until = rrule.validate(rule, sp, all_day=False, timezone=name)
        except InvalidRule:  # start_not_in_rule: the random rule misses its own start
            skipped += 1
            continue
        checked += 1
        got = list(
            instances(
                rule=rule,
                span=sp,
                all_day=False,
                timezone=name,
                window_start=sp.starts_at,
                window_end=sp.starts_at + timedelta(days=800),
                recurrence_until=until,
            )
        )
        assert got and got[0].start == sp.starts_at
        for item in got:
            local = item.start.astimezone(tz).replace(tzinfo=None)
            wanted = datetime.combine(local.date(), start_local.time())
            if local != wanted:  # only a gap may move the wall clock, and then forward
                assert rrule_is_gap(wanted, tz)
                assert local > wanted
            assert item.end - item.start == timedelta(hours=1)
        assert [i.start for i in got] == sorted(i.start for i in got)

    assert checked > 100, (checked, skipped)


def rrule_is_gap(naive, tz):
    return is_nonexistent(naive, tz)


def test_instances_never_walk_past_the_window():
    # an endless rule that never matches must still return
    sp = to_span(
        all_day=False,
        timezone="UTC",
        start="2026-02-28T10:00",
        end="2026-02-28T11:00",
        recurring=True,
    )
    rule = rrule.parse("FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30", all_day=False, timezone="UTC")
    began = time.monotonic()
    got = list(
        instances(
            rule=rule,
            span=sp,
            all_day=False,
            timezone="UTC",
            window_start=utc(2026, 1, 1),
            window_end=utc(2026, 12, 31),
            recurrence_until=None,
        )
    )
    assert got == []
    assert time.monotonic() - began < 1.0


@pytest.mark.parametrize("name", ZONES)
def test_every_instance_is_an_occurrence(name):
    sp = to_span(
        all_day=False,
        timezone=name,
        start="2026-03-02T09:00",
        end="2026-03-02T10:00",
        recurring=True,
    )
    rule = rrule.parse("FREQ=DAILY;COUNT=60", all_day=False, timezone=name)
    until = rrule.validate(rule, sp, all_day=False, timezone=name)
    got = list(
        instances(
            rule=rule,
            span=sp,
            all_day=False,
            timezone=name,
            window_start=utc(2026, 1, 1),
            window_end=utc(2026, 12, 1),
            recurrence_until=until,
        )
    )
    assert len(got) == 60
    for item in got:
        assert is_occurrence(
            item.original_start,
            rule=rule,
            span=sp,
            all_day=False,
            timezone=name,
            recurrence_until=until,
        )
