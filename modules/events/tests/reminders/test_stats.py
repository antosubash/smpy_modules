"""The reminder counts: a user's own, and a tenant's for managers (never who)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_events.core.constants import reminders_limits as limits
from sm_events.core.tenancy import tenant_scope
from sm_events.models import ReminderSent
from sm_events.reminders import stats

from tests.reminders.support import published, world

NOW = datetime(2026, 7, 1, 9, tzinfo=UTC)
U = "11111111-1111-1111-1111-111111111111"


async def _rows(db, *specs):
    """``(recipient, state, code, age)``; the event is one published one."""
    cals = await world(db)
    event = await published(db, cals["U"], title="Talk")
    for n, (who, state, code, age) in enumerate(specs):
        row = ReminderSent(
            event_id=event.id, occurrence_key=f"{event.id}:{n}", starts_at=NOW + timedelta(days=n),
            recipient_id=who, lead_minutes=60, state=state, code=code, claimed_at=NOW - age,
        )  # fmt: skip
        db.add(row)
    await db.flush()


async def test_counts_window_and_unfinished(db):
    m = timedelta(minutes=1)
    await _rows(
        db,
        ("a", "sent", None, 5 * m),
        ("a", "sent", None, timedelta(days=29)),
        ("a", "sent", None, timedelta(days=31)),  # outside the window
        ("a", "failed", "send_failed", 2 * m),
        ("b", "failed", "send_failed", 3 * m),
        ("b", "failed", "send_timeout", 3 * m),
        ("a", "claimed", None, 4 * m),  # not unfinished yet
        ("a", "claimed", None, 6 * m),
        ("a", "sending", None, 4 * m),
        ("b", "sending", None, 6 * m),
        ("a", "sending", None, timedelta(days=40)),  # long ago: outside the window
    )
    got = await stats.counts(db, now=NOW)
    assert got == stats.Counts(sent=2, failed={"send_failed": 2, "send_timeout": 1}, unfinished=2)
    mine = await stats.counts(db, now=NOW, user_id="b")
    assert mine == stats.Counts(sent=0, failed={"send_failed": 1, "send_timeout": 1}, unfinished=1)
    assert await stats.counts(db, now=NOW, user_id="nobody") == stats.Counts(0, {}, 0)
    assert await stats.counts(db, now=NOW, days=1) == stats.Counts(
        sent=1, failed={"send_failed": 2, "send_timeout": 1}, unfinished=2
    )


async def test_the_unfinished_threshold_is_the_constant(db):
    edge = limits.REMINDER_UNFINISHED_AFTER
    await _rows(
        db, ("a", "sending", None, edge), ("a", "sending", None, edge + timedelta(seconds=1))
    )
    assert (await stats.counts(db, now=NOW)).unfinished == 1  # strictly older than the threshold


@pytest.mark.parametrize("spelling", [U, U.upper(), U.replace("-", ""), U.replace("-", "").upper()])
async def test_a_users_counts_match_every_spelling_of_their_id(db, spelling):
    """Rows are written with the canonical id; a read in any spelling finds them."""
    await _rows(
        db,
        (U, "sent", None, timedelta(minutes=5)),
        ("other", "sent", None, timedelta(minutes=5)),
    )
    assert (await stats.counts(db, now=NOW, user_id=spelling)).sent == 1


@pytest.mark.unbound_tenant
async def test_counts_never_cross_tenants(db):
    with tenant_scope("a"):
        await _rows(db, ("x", "sent", None, timedelta(minutes=5)))
    with tenant_scope("b"):
        assert (await stats.counts(db, now=NOW)).sent == 0
    with tenant_scope("a"):
        assert (await stats.counts(db, now=NOW)).sent == 1
