"""Due maths: instants, windows, catch-up and stale rules, across the 2026-2027 clock changes."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sm_events.calendar.times import localize, to_span
from sm_events.core.constants import reminders_limits as limits
from sm_events.reminders import due

NOW = datetime(2026, 7, 1, 8, tzinfo=UTC)


def z(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@pytest.mark.parametrize("lead", limits.REMINDER_LEADS)
def test_due_edges(lead):
    catchup = limits.REMINDER_CATCHUP[lead]
    start = NOW + timedelta(minutes=lead)  # due exactly ``NOW``
    at_catchup = NOW - catchup + timedelta(minutes=lead)
    assert due.is_due(start=at_catchup, lead=lead, now=NOW)  # due == now - catchup: still sent
    assert not due.is_due(start=at_catchup - timedelta(seconds=1), lead=lead, now=NOW)
    assert due.is_stale(start=at_catchup - timedelta(seconds=1), lead=lead, now=NOW)
    assert not due.is_stale(start=at_catchup, lead=lead, now=NOW)
    early = limits.REMINDER_EARLY
    assert due.is_due(start=start + early - timedelta(seconds=1), lead=lead, now=NOW)
    assert not due.is_due(start=start + early, lead=lead, now=NOW)  # not yet: next tick
    assert not due.is_stale(start=start + early, lead=lead, now=NOW)  # nor stale: just early


@pytest.mark.parametrize("lead", limits.REMINDER_LEADS)
def test_never_after_start(lead):
    start = NOW
    assert not due.is_due(start=start, lead=lead, now=NOW)
    assert not due.is_due(start=start, lead=lead, now=NOW + timedelta(seconds=1))
    assert due.is_stale(start=start, lead=lead, now=NOW)
    assert due.is_stale(start=start - timedelta(hours=1), lead=lead, now=NOW)


@pytest.mark.parametrize("lead", limits.REMINDER_LEADS)
def test_window_matches_is_due(lead):
    """``start_window`` is exactly the set of starts ``is_due`` accepts."""
    lo, hi = due.start_window(NOW, lead)
    assert hi - lo == limits.REMINDER_CATCHUP[lead] + limits.REMINDER_EARLY
    assert hi - lo <= timedelta(hours=6, minutes=1)
    one = timedelta(seconds=1)
    assert due.is_due(start=lo, lead=lead, now=NOW)
    assert due.is_due(start=hi - one, lead=lead, now=NOW)
    assert not due.is_due(start=lo - one, lead=lead, now=NOW)
    assert not due.is_due(start=hi, lead=lead, now=NOW)


def test_due_at_is_an_exact_duration():
    start = z("2026-07-01T10:00:00Z")
    assert due.due_at(start, 15) == z("2026-07-01T09:45:00Z")
    assert due.due_at(start, 10080) == z("2026-06-24T10:00:00Z")


# Local 10:00 on the day of each clock change, lead one day: the due instant is exactly 24 h
# earlier in UTC, whatever the wall clock then says. (zone, local day, start UTC, due UTC)
CHANGES = [
    ("Europe/Vienna", "2026-03-29", "2026-03-29T08:00:00Z", "2026-03-28T08:00:00Z"),
    ("Europe/Vienna", "2026-10-25", "2026-10-25T09:00:00Z", "2026-10-24T09:00:00Z"),
    ("Europe/Vienna", "2027-03-28", "2027-03-28T08:00:00Z", "2027-03-27T08:00:00Z"),
    ("Europe/Vienna", "2027-10-31", "2027-10-31T09:00:00Z", "2027-10-30T09:00:00Z"),
    ("America/New_York", "2026-03-08", "2026-03-08T14:00:00Z", "2026-03-07T14:00:00Z"),
    ("America/New_York", "2026-11-01", "2026-11-01T15:00:00Z", "2026-10-31T15:00:00Z"),
    ("America/New_York", "2027-03-14", "2027-03-14T14:00:00Z", "2027-03-13T14:00:00Z"),
    ("America/New_York", "2027-11-07", "2027-11-07T15:00:00Z", "2027-11-06T15:00:00Z"),
    ("Australia/Lord_Howe", "2026-04-05", "2026-04-04T23:30:00Z", "2026-04-03T23:30:00Z"),
    ("Australia/Lord_Howe", "2026-10-04", "2026-10-03T23:00:00Z", "2026-10-02T23:00:00Z"),
    ("Australia/Lord_Howe", "2027-04-04", "2027-04-03T23:30:00Z", "2027-04-02T23:30:00Z"),
    ("Australia/Lord_Howe", "2027-10-03", "2027-10-02T23:00:00Z", "2027-10-01T23:00:00Z"),
]


@pytest.mark.parametrize(("zone", "day", "start", "expected"), CHANGES)
def test_one_day_lead_across_every_clock_change(zone, day, start, expected):
    tz = ZoneInfo(zone)
    begin = localize(datetime.combine(date.fromisoformat(day), time(10)), tz)
    assert begin == z(start)  # the table is the zone's own arithmetic
    assert due.due_at(begin, 1440) == z(expected)
    assert due.due_at(begin, 1440) == begin - timedelta(hours=24)


ALL_DAY = [
    ("Europe/Vienna", "2026-07-06", "2026-07-05T22:00:00Z", "2026-07-04T22:00:00Z"),
    ("Europe/Vienna", "2026-03-29", "2026-03-28T23:00:00Z", "2026-03-27T23:00:00Z"),
    ("Europe/Vienna", "2026-10-25", "2026-10-24T22:00:00Z", "2026-10-23T22:00:00Z"),
    ("America/New_York", "2026-03-08", "2026-03-08T05:00:00Z", "2026-03-07T05:00:00Z"),
    ("America/New_York", "2027-11-07", "2027-11-07T04:00:00Z", "2027-11-06T04:00:00Z"),
    ("Australia/Lord_Howe", "2026-10-04", "2026-10-03T13:30:00Z", "2026-10-02T13:30:00Z"),
    ("Australia/Lord_Howe", "2027-04-04", "2027-04-03T13:00:00Z", "2027-04-02T13:00:00Z"),
]


@pytest.mark.parametrize(("zone", "day", "start", "expected"), ALL_DAY)
def test_all_day_start_is_local_midnight_of_the_events_zone(zone, day, start, expected):
    """An all-day event "starts" at local midnight of ITS zone (its stored ``starts_at``), so a
    one-day lead is exactly 24 h before that instant."""
    span = to_span(all_day=True, timezone=zone, start=day, end=day, recurring=False)
    assert span.starts_at == z(start)
    assert due.due_at(span.starts_at, 1440) == z(expected)


def test_gap_instance_uses_shifted_start():
    """Daily 02:30 Vienna: on 29 March 02:30 does not exist and the instance is shifted to
    03:30 CEST (01:30Z); a 15-minute lead is due 01:15Z."""
    shifted = localize(datetime(2026, 3, 29, 2, 30), ZoneInfo("Europe/Vienna"))
    assert shifted == z("2026-03-29T01:30:00Z")
    assert due.due_at(shifted, 15) == z("2026-03-29T01:15:00Z")


def test_fold_instance_takes_the_first_occurrence():
    """25 October 02:30 happens twice in Vienna; the first (CEST, 00:30Z) is the instance."""
    first = localize(datetime(2026, 10, 25, 2, 30), ZoneInfo("Europe/Vienna"))
    assert first == z("2026-10-25T00:30:00Z")
    assert due.due_at(first, 60) == z("2026-10-24T23:30:00Z")


def test_next_due():
    starts = [NOW + timedelta(days=3), NOW + timedelta(days=10), NOW + timedelta(days=17)]
    # Three days ahead is closer than a week: that one is too late, the next is not.
    assert due.next_due(starts, 10080, NOW) == starts[1] - timedelta(minutes=10080)
    assert due.next_due(starts, 1440, NOW) == starts[0] - timedelta(minutes=1440)
    assert due.next_due(starts, 60, NOW) == starts[0] - timedelta(minutes=60)
    assert due.next_due([], 60, NOW) is None
    assert due.next_due([NOW - timedelta(days=1)], 60, NOW) is None  # started
    # Due a moment ago, still inside the catch-up: it is the next one, and it is sent at once.
    soon = NOW + timedelta(minutes=60) - timedelta(minutes=1)
    assert due.next_due([soon], 60, NOW) == soon - timedelta(minutes=60)
    # Due longer ago than the catch-up: stale, so the following one.
    late = NOW + timedelta(minutes=60) - limits.REMINDER_CATCHUP[60] - timedelta(seconds=1)
    assert due.next_due([late, late + timedelta(days=1)], 60, NOW) == (
        late + timedelta(days=1) - timedelta(minutes=60)
    )


def test_next_due_takes_an_iterator_and_stops_early():
    pulled = []

    def starts():
        for i in range(1, 1000):
            pulled.append(i)
            yield NOW + timedelta(days=i)

    assert due.next_due(starts(), 1440, NOW) is not None
    assert len(pulled) == 1  # an endless series is never walked
