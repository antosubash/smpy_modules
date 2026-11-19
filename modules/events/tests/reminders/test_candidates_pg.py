"""The candidate statements on Postgres: a fixed number of them, and each served by an index."""

from __future__ import annotations

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


async def test_prefilters_are_served_by_indexes(db, db_state):
    await _seed(db, 3, 2)
    await db.commit()
    seen, stop = _record(db_state.engine)
    try:
        await candidates.candidates(db, now=NOW)
    finally:
        stop()
    await db.rollback()  # no open transaction may hold a lock the DDL below waits for
    ours = [(s, p) for s, p in seen if "events_follow" in s and "events_event" in s]
    assert ours, "no prefilter statement was captured"
    plans = []
    async with db_state.engine.connect() as conn:
        # On three rows the planner prefers any index to the one the statement is written for
        # (``status = 'published'``; the older calendar-first range index, which can only scan a
        # tenant's whole slice for a time window): take those away, and forbid seq scans, in
        # a transaction that is rolled back. What is left is what the statements can be served by.
        await conn.exec_driver_sql("DROP INDEX ix_events_event_publish_due, ix_events_event_range")
        await conn.exec_driver_sql("SET LOCAL enable_seqscan = off")
        for statement, params in ours:
            rows = await conn.exec_driver_sql("EXPLAIN " + statement, params)
            plans.append("\n".join(r[0] for r in rows))
        await conn.rollback()
    text = "\n".join(plans)
    assert "ix_events_event_start" in text  # one-offs: the window, not every event
    assert "ix_events_follow_lead" in text  # series: one lead's follows, not every follow
    assert "Seq Scan on events_follow" not in text
    assert "Seq Scan on events_event" not in text
