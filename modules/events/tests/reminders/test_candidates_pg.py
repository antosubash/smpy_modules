"""The candidate statements on Postgres: a fixed number of them, and each served by an index."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from sm_events.reminders import candidates
from sqlalchemy import event as sa_event

from tests.pg_support import USING_POSTGRES
from tests.reminders.support import bulk_follows, world
from tests.reminders.test_candidates import NOW, TEN
from tests.support.calendars import seed_event, seed_series

pytestmark = pytest.mark.skipif(not USING_POSTGRES, reason="Postgres plans and statement counts")


def _record(engine):
    seen: list[tuple[str, object]] = []

    def hook(_conn, _cursor, statement, parameters, _context, _many):
        seen.append((statement, parameters))

    target = engine.sync_engine
    sa_event.listen(target, "before_cursor_execute", hook)
    return seen, lambda: sa_event.remove(target, "before_cursor_execute", hook)


async def _seed(db, n_events: int, n_followers: int, cals=None):
    cals = cals or await world(db)
    for i in range(n_events):
        event = await seed_event(
            db, cals["U"], title=f"E{i}", status="published", starts_at=TEN,
            ends_at=TEN + timedelta(hours=1),
        )  # fmt: skip
        await bulk_follows(db, event.id, [f"u{j}" for j in range(n_followers)])
        await bulk_follows(db, event.id, ["u0"], lead=15)
    series = await seed_series(
        db, cals["U"], "FREQ=DAILY", "2026-01-01T10:00", "2026-01-01T11:00", tz="UTC",
        status="published", title="Daily",
    )  # fmt: skip
    await bulk_follows(db, series.id, ["u0"])
    await db.flush()
    return cals


async def test_statement_count_does_not_grow_with_follows(db, db_state):
    cals = await _seed(db, 5, 2)
    seen, stop = _record(db_state.engine)
    try:
        await candidates.candidates(db, now=NOW)
    finally:
        stop()
    small = len(seen)
    await _seed(db, 300, 20, cals)
    seen.clear()
    seen2, stop = _record(db_state.engine)
    try:
        got, _ = await candidates.candidates(db, now=NOW)
    finally:
        stop()
    assert len(got) > 300  # the work grew ...
    assert len(seen2) <= small + 1  # ... the statements did not (one more: the follower count)
    assert small <= 30


async def test_the_window_statement_reads_only_the_window(db, db_state):
    """With real volumes (5,000 followed one-offs spread over a week, statistics gathered), the
    one-off prefilter is served by the window index and touches a handful of rows, not every
    event and not every follow."""
    from sm_events.models import Event, EventFollow

    cals = await world(db)
    cal = cals["U"]
    events = [
        Event(
            calendar_id=cal.id, uid=f"{i}@x", starts_at=TEN + timedelta(minutes=2 * i - 5000),
            ends_at=TEN + timedelta(minutes=2 * i - 4999), timezone="UTC", status="published",
        )
        for i in range(5000)
    ]  # fmt: skip
    db.add_all(events)
    await db.flush()
    db.add_all(
        EventFollow(event_id=e.id, user_id="u", lead_minutes=60, locale="en") for e in events
    )
    await db.commit()
    async with db_state.engine.connect() as conn:
        await conn.exec_driver_sql("ANALYZE events_event")
        await conn.exec_driver_sql("ANALYZE events_follow")
        await conn.commit()
    seen, stop = _record(db_state.engine)
    try:
        got, _ = await candidates.candidates(db, now=NOW)
    finally:
        stop()
    await db.rollback()
    assert len(got) == 8  # the window is 16 minutes wide: eight starts, two minutes apart
    one_off = next(
        (s, p)
        for s, p in seen
        if "events_follow" in s and "events_event" in s and "rrule IS NULL" in s
    )
    async with db_state.engine.connect() as conn:
        rows = await conn.exec_driver_sql("EXPLAIN (ANALYZE, COSTS OFF) " + one_off[0], one_off[1])
        plan = "\n".join(r[0] for r in rows)
        await conn.rollback()
    assert "ix_events_event_start" in plan, plan
    assert "Seq Scan" not in plan, plan
    touched = [int(n) for n in re.findall(r"actual time=[\d.]+\.\.[\d.]+ rows=(\d+)", plan)]
    assert max(touched) <= 20, plan  # never thousands: the window, not the table


async def test_the_series_statement_is_served_by_the_follow_index(db, db_state):
    """A series is found by walking one lead's follows through their index, never a table scan
    (the cost per tick is one narrow expansion per followed series, by design)."""
    cals = await _seed(db, 3, 2)
    await db.commit()
    seen, stop = _record(db_state.engine)
    try:
        await candidates.candidates(db, now=NOW)
    finally:
        stop()
    await db.rollback()
    series = next(
        (s, p)
        for s, p in seen
        if "events_follow" in s and "rrule IS NOT NULL" in s and "DISTINCT" in s
    )
    async with db_state.engine.connect() as conn:
        await conn.exec_driver_sql("SET LOCAL enable_seqscan = off")
        rows = await conn.exec_driver_sql("EXPLAIN " + series[0], series[1])
        plan = "\n".join(r[0] for r in rows)
        await conn.rollback()
    assert "ix_events_follow_lead" in plan, plan
    assert "Seq Scan on events_follow" not in plan, plan
    assert cals
