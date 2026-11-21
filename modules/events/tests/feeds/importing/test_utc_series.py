"""A series' wall clock is what its file says: UTC stays UTC, a TZID stays on its zone.

Differential: the instants the module expands from an imported series equal dateutil's, for both
DST changes of five calendar zones.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from dateutil import rrule as du
from sm_events.calendar import rrule
from sm_events.calendar.expand import instances
from sm_events.calendar.times import Span, to_span

from tests.feeds.importing.mapping import event, mapped, one

ZONES = ["Europe/Vienna", "America/New_York", "Australia/Sydney", "Asia/Kolkata", "UTC"]
RULES = [
    "FREQ=WEEKLY;BYDAY=WE;COUNT=60",
    "FREQ=DAILY;INTERVAL=3;COUNT=120",
    "FREQ=MONTHLY;BYMONTHDAY=11;COUNT=24",
]
FIRST = datetime(2026, 2, 11, 9, tzinfo=UTC)  # a Wednesday


def expand(item) -> list[datetime]:
    e = item.event
    span = to_span(
        all_day=False,
        timezone=e.times.timezone,
        start=e.times.start,
        end=e.times.end,
        recurring=True,
    )
    rule = rrule.parse(e.rrule, all_day=False, timezone=e.times.timezone)
    until = rrule.validate(rule, span, all_day=False, timezone=e.times.timezone)
    found = instances(
        rule=rule,
        span=Span(span.starts_at, span.ends_at),
        all_day=False,
        timezone=e.times.timezone,
        window_start=FIRST - timedelta(days=1),
        window_end=FIRST + timedelta(days=1500),
        recurrence_until=until,
    )
    return [i.start for i in found]


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("rule", RULES)
def test_a_utc_series_matches_dateutil_across_both_dst_changes(zone, rule):
    start = FIRST.strftime("%Y%m%dT%H%M%SZ")
    end = (FIRST + timedelta(hours=2)).strftime("%Y%m%dT%H%M%SZ")
    item = one(*event("s@x", f"RRULE:{rule}", start=start, end=end), tz=zone)
    assert item.event is not None and "kept_utc" in item.notes
    assert item.event.times.timezone == "UTC"
    want = list(du.rrulestr(rule, dtstart=FIRST))
    assert expand(item) == want  # every instant, in UTC, as dateutil has it


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("rule", RULES)
def test_a_tzid_series_keeps_its_wall_clock_like_dateutil(zone, rule):
    vienna = ZoneInfo("Europe/Vienna")
    local = datetime(2026, 2, 11, 10, tzinfo=vienna)
    lines = event(
        "s@x",
        f"RRULE:{rule}",
        dtstart="DTSTART;TZID=Europe/Vienna:20260211T100000",
    )
    lines[3] = "DTEND;TZID=Europe/Vienna:20260211T120000"
    item = one(*lines, tz=zone)
    assert item.event is not None and item.event.times.timezone == "Europe/Vienna"
    assert "kept_utc" not in item.notes
    want = [d.astimezone(UTC) for d in du.rrulestr(rule, dtstart=local)]
    assert expand(item) == want


def test_a_utc_one_off_is_still_shown_in_the_calendar_zone():
    item = one(*event("o@x"), tz="Europe/Vienna")  # 2026-07-01 10:00Z
    assert item.event is not None and "kept_utc" not in item.notes
    assert (item.event.times.timezone, item.event.times.start) == (
        "Europe/Vienna",
        "2026-07-01T12:00",
    )


def test_the_reviewers_minimal_case():
    item = one(
        *event(
            "s@x",
            "RRULE:FREQ=WEEKLY;BYDAY=WE;UNTIL=20270210T000000Z",
            start="20260211T090000Z",
            end="20260211T120000Z",
        ),
        tz="Europe/Vienna",
    )
    april = [s for s in expand(item) if s.month == 4 and s.day == 1]
    assert april == [datetime(2026, 4, 1, 9, tzinfo=UTC)]  # not 08:00Z


def test_utc_exdates_and_children_match_by_instant_across_the_change():
    lines = event(
        "s@x",
        "RRULE:FREQ=WEEKLY;BYDAY=WE;COUNT=20",
        "EXDATE:20260401T090000Z",
        start="20260211T090000Z",
        end="20260211T100000Z",
    )
    child = [
        "BEGIN:VEVENT",
        "UID:s@x",
        "RECURRENCE-ID:20260408T090000Z",
        "DTSTART:20260408T120000Z",
        "DTEND:20260408T130000Z",
        "END:VEVENT",
    ]
    got = mapped(*lines, *child, tz="Europe/Vienna")
    (series,) = got.items
    overrides = {(o.original_start, o.kind) for o in series.event.overrides}  # type: ignore[union-attr]
    assert overrides == {
        (datetime(2026, 4, 1, 9, tzinfo=UTC), "skipped"),
        (datetime(2026, 4, 8, 9, tzinfo=UTC), "moved"),
    }
    assert "exdate_ignored" not in series.notes and "override_dropped" not in series.notes
