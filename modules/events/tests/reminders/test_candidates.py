"""Which reminders are due now: bounded reads through the module's own occurrences read."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from sm_events.calendar.times import localize
from sm_events.core.tenancy import tenant_scope
from sm_events.models import OccurrenceOverride
from sm_events.reminders import candidates, limits

from tests.reminders.support import bulk_follows, follow_row, published, world
from tests.support.calendars import seed_event, seed_series

NOW = datetime(2026, 7, 1, 9, tzinfo=UTC)
TEN = datetime(2026, 7, 1, 10, tzinfo=UTC)  # a start one hour after NOW


async def _cands(db, now=NOW, cap=limits.REMINDER_CANDIDATES_MAX):
    return await candidates.candidates(db, now=now, cap=cap)


async def _one_off(db, cal, starts_at=TEN, users=("u",), leads=(60,), **fields):
    event = await published(
        db, cal, starts_at=starts_at, ends_at=starts_at + timedelta(hours=1), **fields
    )
    for user in users:
        for lead in leads:
            db.add(follow_row(event, user=user, lead=lead))
    await db.flush()
    return event


async def _weekly(db, cal, *, users=("u",), lead=60, start="2026-06-24T10:00", **fields):
    event = await seed_series(
        db, cal, "FREQ=WEEKLY", start, start[:11] + "11:00", tz="UTC", status="published",
        title="Weekly", **fields,
    )  # fmt: skip
    for user in users:
        db.add(follow_row(event, user=user, lead=lead))
    await db.flush()
    return event


async def test_one_off_due_per_lead(db):
    cals = await world(db)
    event = await _one_off(db, cals["U"], leads=(15, 60))
    got, deferred = await _cands(db)
    assert deferred == 0
    assert [(c.event_id, c.lead, c.start, c.user_id) for c in got] == [(event.id, 60, TEN, "u")]
    assert got[0].occurrence_key == str(event.id) and got[0].locale == "en"
    assert got[0].revision == event.revision and got[0].end == TEN + timedelta(hours=1)
    assert got[0].due == NOW
    later, _ = await _cands(db, now=NOW + timedelta(minutes=45))
    assert [(c.lead, c.due) for c in later] == [(15, NOW + timedelta(minutes=45))]
    # The hour lead has gone by: stale, never sent late.
    assert (await _cands(db, now=NOW + timedelta(minutes=16)))[0] == []


async def test_nothing_before_the_window_and_nothing_after_the_start(db):
    cals = await world(db)
    await _one_off(db, cals["U"])
    assert (await _cands(db, now=NOW - timedelta(minutes=2)))[0] == []  # a tick too early
    assert (await _cands(db, now=NOW - timedelta(seconds=30)))[0] != []  # inside one beat
    assert (await _cands(db, now=TEN))[0] == []
    assert (await _cands(db, now=TEN + timedelta(minutes=1)))[0] == []


async def test_series_instance_key(db):
    cals = await world(db)
    event = await _weekly(db, cals["U"])
    got, _ = await _cands(db)
    assert [c.occurrence_key for c in got] == [f"{event.id}:20260701T100000Z"]
    assert got[0].start == TEN
    # Next week's instance, and only it.
    next_week, _ = await _cands(db, now=NOW + timedelta(days=7))
    assert [c.occurrence_key for c in next_week] == [f"{event.id}:20260708T100000Z"]


async def test_all_day_start_is_local_midnight(db):
    cals = await world(db)
    event = await seed_series(
        db, cals["U"], "FREQ=WEEKLY", "2026-06-29", "2026-06-29", tz="Europe/Vienna",
        all_day=True, status="published", title="Day",
    )  # fmt: skip
    db.add(follow_row(event, lead=1440))
    await db.flush()
    midnight = localize(datetime(2026, 7, 6), __import__("zoneinfo").ZoneInfo("Europe/Vienna"))
    assert midnight == datetime(2026, 7, 5, 22, tzinfo=UTC)
    got, _ = await _cands(db, now=midnight - timedelta(days=1))
    assert [(c.start, c.lead) for c in got] == [(midnight, 1440)]


@pytest.mark.parametrize(
    "case", ["cancelled", "skipped", "event_cancelled", "draft", "in_review", "scheduled",
             "trashed", "calendar_trashed"],
)  # fmt: skip
async def test_candidate_filters(db, case):
    cals = await world(db)
    cal = cals["U"]
    fields = {"cancelled": True} if case == "event_cancelled" else {}
    status = {"draft": "draft", "in_review": "in_review", "scheduled": "draft"}.get(case)
    if status:
        fields["status"] = status
    if case == "scheduled":
        fields["publish_at"] = datetime(2030, 1, 1, tzinfo=UTC)
    if case in ("cancelled", "skipped"):
        event = await _weekly(db, cal)
        db.add(OccurrenceOverride(event_id=event.id, original_start=TEN, kind=case))
    else:
        event = await _one_off(db, cal, **fields)
    await db.flush()
    if case == "trashed":
        await db.delete(event)
    if case == "calendar_trashed":
        await db.delete(cal)
    await db.flush()
    assert (await _cands(db))[0] == []


async def test_the_control_case_is_a_candidate(db):
    """Every filter above removes a candidate that would otherwise be there."""
    cals = await world(db)
    await _one_off(db, cals["U"])
    event = await _weekly(db, cals["I"])
    assert len((await _cands(db))[0]) == 2
    assert event


async def test_moved_into_window(db):
    cals = await world(db)
    event = await _weekly(db, cals["U"], start="2026-06-17T10:00")  # instances Wed 17, 24, Jul 1
    db.add(
        OccurrenceOverride(
            event_id=event.id,
            original_start=datetime(2026, 7, 8, 10, tzinfo=UTC),
            kind="moved",
            starts_at=TEN,
            ends_at=TEN + timedelta(hours=1),
        )
    )
    await db.flush()
    got, _ = await _cands(db)
    keys = sorted(c.occurrence_key for c in got)
    # The regular instance at TEN and the one moved into it: two occurrences, two keys.
    assert keys == [f"{event.id}:20260701T100000Z", f"{event.id}:20260708T100000Z"]
    assert {c.start for c in got} == {TEN}


async def test_moved_out_of_window_not_at_old_time(db):
    cals = await world(db)
    event = await _weekly(db, cals["U"])
    later = TEN + timedelta(days=2)
    db.add(
        OccurrenceOverride(
            event_id=event.id, original_start=TEN, kind="moved",
            starts_at=later, ends_at=later + timedelta(hours=1),
        )
    )  # fmt: skip
    await db.flush()
    assert (await _cands(db))[0] == []  # not at the old time
    at_new, _ = await _cands(db, now=later - timedelta(hours=1))
    assert [(c.occurrence_key, c.start) for c in at_new] == [
        (f"{event.id}:20260701T100000Z", later)  # reminded once, at the NEW time, original key
    ]


async def test_expansion_is_window_bounded(db, monkeypatch):
    """An endless daily series with 10,000 followers: fast, capped, deferred counted, and the
    expansion is asked for the one event, once, over a window of a few hours."""
    cals = await world(db)
    event = await seed_series(
        db, cals["U"], "FREQ=DAILY", "2020-01-01T10:00", "2020-01-01T11:00", tz="UTC",
        status="published", title="Daily",
    )  # fmt: skip
    await bulk_follows(db, event.id, [f"user{i}" for i in range(10_000)])
    await db.flush()
    seen = []
    real = candidates.occurrences

    async def spy(*args, **kwargs):
        seen.append((kwargs["start"], kwargs["end"], kwargs["filters"].event_ids))
        page = await real(*args, **kwargs)
        assert len(page.items) <= 2  # the window holds one instance, plus a neighbour at most
        return page

    monkeypatch.setattr(candidates, "occurrences", spy)
    began = time.perf_counter()
    got, deferred = await _cands(db, cap=1000)
    assert time.perf_counter() - began < 3
    assert len(got) == 1000 and deferred == 9000
    assert [c.user_id for c in got] == sorted(c.user_id for c in got)  # a stable order
    assert len(seen) == 1 and seen[0][2] == frozenset({event.id})
    assert seen[0][1] - seen[0][0] <= timedelta(hours=6, minutes=1)


async def test_candidates_cap(db):
    cals = await world(db)
    for i in range(300):
        await seed_event(
            db, cals["U"], title=f"E{i}", status="published", starts_at=TEN,
            ends_at=TEN + timedelta(hours=1),
        )  # fmt: skip
    from sm_events.models import Event
    from sqlalchemy import select

    ids = (await db.execute(select(Event.id))).scalars().all()
    for event_id in ids:
        await bulk_follows(db, event_id, ["a", "b", "c"])
    await db.flush()
    got, deferred = await _cands(db, cap=250)
    assert len(got) == 250 and deferred == 900 - 250
    assert [c.due for c in got] == sorted(c.due for c in got)
    keys = [(c.event_id, c.user_id) for c in got]
    assert len(set(keys)) == 250


@pytest.mark.unbound_tenant
async def test_other_tenant_follows_ignored(db):
    with tenant_scope("a"):
        cals = await world(db)
        await _one_off(db, cals["U"])
        await db.flush()
    with tenant_scope("b"):
        assert (await _cands(db))[0] == []
    with tenant_scope("a"):
        assert len((await _cands(db))[0]) == 1


async def test_impossible_rule_terminates(db):
    cals = await world(db)
    event = await seed_series(
        db, cals["U"], "FREQ=YEARLY", "2026-02-27T10:00", "2026-02-27T11:00", tz="UTC",
        status="published", title="Odd",
    )  # fmt: skip
    event.rrule = "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30"
    db.add(follow_row(event))
    await db.flush()
    began = time.perf_counter()
    assert (await _cands(db))[0] == []
    assert time.perf_counter() - began < 1


async def test_no_follows_no_work(db, monkeypatch):
    await world(db)

    async def boom(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("read with nothing followed")

    monkeypatch.setattr(candidates, "occurrences", boom)
    assert await _cands(db) == ([], 0)
