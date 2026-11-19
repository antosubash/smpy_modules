"""Candidates, part two: ordering and the coming starts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_events.reminders import candidates
from sm_events.reminders.candidates import Candidate

from tests.reminders.support import world
from tests.reminders.test_candidates import NOW, TEN, _cands, _one_off, _weekly
from tests.support.calendars import seed_series


async def test_candidate_orders_and_is_frozen(db):
    cals = await world(db)
    await _one_off(db, cals["U"], users=("b", "a"), leads=(15, 60), starts_at=TEN)
    got, _ = await _cands(db, now=NOW + timedelta(minutes=45))
    assert [(c.lead, c.user_id) for c in got] == [(15, "a"), (15, "b")]
    with pytest.raises(AttributeError):
        got[0].lead = 1  # type: ignore[misc]
    assert isinstance(got[0], Candidate)


async def test_next_start_and_next_starts(db):
    cals = await world(db)
    weekly = await _weekly(db, cals["U"])
    one = await _one_off(db, cals["U"], starts_at=NOW + timedelta(days=3))
    got = await candidates.next_starts(db, [weekly, one], now=NOW)
    assert got[one.id][0] == NOW + timedelta(days=3)
    assert got[weekly.id][:2] == [TEN, TEN + timedelta(days=7)]
    assert all(b > a for a, b in zip(got[weekly.id], got[weekly.id][1:], strict=False))
    # Sparse rules are found past the first window.
    yearly = await seed_series(
        db, cals["U"], "FREQ=YEARLY", "2025-12-24T10:00", "2025-12-24T11:00", tz="UTC",
        status="published", title="Xmas",
    )  # fmt: skip
    far = await candidates.next_starts(db, [yearly], now=NOW)
    assert far[yearly.id] == [datetime(2026, 12, 24, 10, tzinfo=UTC)]
    done = await _one_off(db, cals["U"], starts_at=NOW - timedelta(days=3), title="Done")
    assert (await candidates.next_starts(db, [done], now=NOW))[done.id] == []
