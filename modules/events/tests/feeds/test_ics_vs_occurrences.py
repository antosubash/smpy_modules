"""The instants an ICS client computes from a feed equal the occurrences read's.

A client expands ``RRULE`` on the wall clock of ``DTSTART;TZID=...`` (``dateutil`` does exactly
that), removes ``EXDATE`` instances and lets a ``RECURRENCE-ID`` component replace or cancel
its instance. That is done here on the parsed feed and compared, instance for instance, with
what the occurrences read returns, across both DST changes of 2026 (29 March, 25 October).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import icalendar
import pytest
from dateutil import rrule as du
from sm_events.calendar.times import localize
from sm_events.feeds.ics_event import FeedEvent, components
from sm_events.models import OccurrenceOverride

from tests.support.access import principal, seed_calendars
from tests.support.calendars import seed_series
from tests.support.occurrences import read, utc

VIENNA = ZoneInfo("Europe/Vienna")
ANON = principal(None)


def _client_instances(
    item: FeedEvent, horizon: datetime
) -> dict[object, tuple[object, object, str]]:
    """``{original instance: (start, end, status)}`` as a calendar client would show them."""
    cal = icalendar.Calendar()
    for c in components(item):
        cal.add_component(c)
    parsed = list(icalendar.Calendar.from_ical(cal.to_ical()).walk("VEVENT"))
    master = next(e for e in parsed if "RECURRENCE-ID" not in e)
    start = master["DTSTART"].dt
    length = master["DTEND"].dt - start
    rule = du.rrulestr(master["RRULE"].to_ical().decode(), dtstart=start)
    if isinstance(start, datetime):
        stop = horizon.astimezone(start.tzinfo)
        instances = list(rule.between(start - timedelta(days=1), stop, inc=True))
    else:
        instances = [d.date() for d in rule if d.date() < horizon.date()]
    exdate = master.get("EXDATE")
    skipped = {x.dt for x in exdate.dts} if exdate is not None else set()
    shown: dict[object, tuple[object, object, str]] = {}
    for instance in instances:
        if instance in skipped:
            continue
        shown[instance] = (instance, instance + length, "confirmed")
    for e in parsed:
        if "RECURRENCE-ID" not in e:
            continue
        rid = e["RECURRENCE-ID"].dt
        assert rid in shown, "a RECURRENCE-ID must name a real instance"
        status = "cancelled" if str(e["STATUS"]) == "CANCELLED" else "confirmed"
        shown[rid] = (e["DTSTART"].dt, e["DTEND"].dt, status)
    return shown


def _as_utc(value) -> datetime:
    return value.astimezone(UTC)


async def _fixture(db, *, all_day: bool):
    cals = await seed_calendars(db)
    if all_day:
        ev = await seed_series(
            db, cals["U"], "FREQ=WEEKLY;COUNT=40", "2026-03-02", "2026-03-03",
            all_day=True, status="published",
        )  # fmt: skip
    else:
        ev = await seed_series(
            db, cals["U"], "FREQ=WEEKLY;COUNT=40", "2026-03-02T10:00", "2026-03-02T11:00",
            status="published",
        )  # fmt: skip
    return ev


def _local(y: int, m: int, d: int, h: int) -> datetime:
    return localize(datetime(y, m, d, h), VIENNA)


def _week(n: int, all_day: bool) -> datetime:
    return localize(datetime(2026, 3, 2, 0 if all_day else 10) + timedelta(weeks=n - 1), VIENNA)


async def _overrides(db, ev, all_day: bool):
    rows = [
        OccurrenceOverride(
            event_id=ev.id, original_start=_week(4, all_day), kind="skipped"
        ),  # 23 Mar
        OccurrenceOverride(
            event_id=ev.id, original_start=_week(5, all_day), kind="cancelled"
        ),  # 30 Mar, after DST
        OccurrenceOverride(
            event_id=ev.id,
            original_start=_week(34, all_day),  # 26 Oct, the first Monday after the autumn change
            kind="moved",
            starts_at=_local(2026, 10, 27, 0 if all_day else 11),
            ends_at=_local(2026, 10, 28 if all_day else 27, 0 if all_day else 12),
        ),
        OccurrenceOverride(
            event_id=ev.id, original_start=_week(30, all_day), kind="cancelled"
        ),  # 28 Sep
    ]
    db.add_all(rows)
    await db.flush()
    return rows


@pytest.mark.parametrize("all_day", [False, True], ids=["timed", "all-day"])
async def test_client_instants_equal_the_occurrences_read(db, all_day):
    ev = await _fixture(db, all_day=all_day)
    rows = await _overrides(db, ev, all_day)
    from sm_events.models import EventText
    from sqlalchemy import select

    text = (await db.execute(select(EventText).where(EventText.event_id == ev.id))).scalar_one()
    item = FeedEvent(ev, text, rows, "https://x.example/e", None, None)

    horizon = utc(2027, 1, 1)
    shown = _client_instances(item, horizon)
    page = await read(db, ANON, utc(2026, 2, 1), utc(2026, 12, 31))
    ours = [o for o in page.items if o.event_id == ev.id]
    assert len(ours) >= 35 and not page.truncated

    if all_day:
        expect = sorted((o.start_date, o.end_date, o.status) for o in ours)
        got = sorted((s, e, st) for s, e, st in shown.values())
    else:
        expect = sorted((o.start, o.end, o.status) for o in ours)
        got = sorted((_as_utc(s), _as_utc(e), st) for s, e, st in shown.values())
    assert got == expect


async def test_the_series_crosses_both_dst_changes(db):
    """Guard for the test above: it really spans 29 March and 25 October, and a client's
    10:00 Vienna is 09:00Z before and 08:00Z in summer, 09:00Z again after October."""
    ev = await _fixture(db, all_day=False)
    page = await read(db, ANON, utc(2026, 2, 1), utc(2026, 12, 31))
    hours = {(o.start.month, o.start.hour) for o in page.items if o.event_id == ev.id}
    assert (3, 9) in hours and (4, 8) in hours and (10, 8) in hours and (11, 9) in hours
    local = {o.start.astimezone(VIENNA) for o in page.items if o.event_id == ev.id}
    assert all(t.hour == 10 for t in local)  # the wall clock never moves
    assert date(2026, 10, 26) in {t.date() for t in local}
