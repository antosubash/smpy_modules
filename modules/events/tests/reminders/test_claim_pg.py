"""The claim with real concurrency: separate sessions racing on Postgres."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Event, ReminderSent
from sm_events.reminders import claim as ledger
from sm_events.reminders import limits
from sm_events.reminders.candidates import Candidate
from sqlalchemy import func, select, update

from tests.pg_support import USING_POSTGRES
from tests.reminders.support import published, world

pytestmark = pytest.mark.skipif(not USING_POSTGRES, reason="needs real concurrent transactions")

NOW = datetime(2026, 7, 1, 9, tzinfo=UTC)
START = datetime(2026, 7, 1, 10, tzinfo=UTC)
RACERS = 20


@pytest.fixture
async def one(db_state):
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            cals = await world(db)
            event = await published(db, cals["U"], title="Talk", starts_at=START)
            candidate = Candidate(
                event.id, event.revision, str(event.id), START, START + timedelta(hours=1),
                60, "u", "en",
            )  # fmt: skip
            await db.commit()
    return db_state, candidate


async def _count(state, **where) -> int:
    with tenant_scope("default"):
        async with state.session_factory() as db:
            stmt = select(func.count()).select_from(ReminderSent)
            return (await db.execute(stmt)).scalar_one()


async def test_claim_once_under_race(one):
    state, c = one
    with tenant_scope("default"):
        got = await asyncio.gather(
            *(
                ledger.claim(state.session_factory, c, tenant_id="default", now=NOW)
                for _ in range(RACERS)
            )
        )
    winners = [g for g in got if g is not None]
    assert len(winners) == 1
    assert await _count(state) == 1


async def test_many_recipients_race_independently(one):
    """Distinct recipients are distinct claims: contention on one row never blocks another."""
    state, c = one
    users = [replace(c, user_id=f"user{i}") for i in range(RACERS)]
    with tenant_scope("default"):
        got = await asyncio.gather(
            *(
                ledger.claim(state.session_factory, u, tenant_id="default", now=NOW)
                for u in users + users  # every claim twice, all at once
            )
        )
    assert sum(g is not None for g in got) == RACERS
    assert await _count(state) == RACERS


async def test_reclaim_under_race(one):
    state, c = one
    first = await ledger.claim(state.session_factory, c, tenant_id="default", now=NOW)
    later = NOW + limits.REMINDER_CLAIM_LEASE + timedelta(seconds=1)
    with tenant_scope("default"):
        got = await asyncio.gather(
            *(
                ledger.claim(state.session_factory, c, tenant_id="default", now=later)
                for _ in range(RACERS)
            )
        )
    winners = [g for g in got if g is not None]
    assert len(winners) == 1 and winners[0].id == first.id and winners[0].claimed_at == later
    assert await ledger.begin_send(state.session_factory, "default", first) is False


async def test_begin_send_under_race(one):
    """Two holders of one claim (the lease passed under a slow one): only the current may send."""
    state, c = one
    first = await ledger.claim(state.session_factory, c, tenant_id="default", now=NOW)
    later = NOW + limits.REMINDER_CLAIM_LEASE + timedelta(seconds=1)
    second = await ledger.claim(state.session_factory, c, tenant_id="default", now=later)
    with tenant_scope("default"):
        got = await asyncio.gather(
            *(
                ledger.begin_send(state.session_factory, "default", who)
                for who in (first, second) * 5
            )
        )
    assert sum(got) == 1


async def test_guard_serialises_with_cancel(one):
    """A cancel holding the event row makes the claim wait; once it commits the claim is None."""
    state, c = one
    with tenant_scope("default"):
        async with state.session_factory() as canceller:
            await canceller.execute(
                update(Event).where(Event.id == c.event_id).values(cancelled=True)
            )  # holds the row lock, uncommitted
            pending = asyncio.ensure_future(
                ledger.claim(state.session_factory, c, tenant_id="default", now=NOW)
            )
            await asyncio.sleep(0.5)
            assert not pending.done()  # waiting on the cancel, not racing past it
            await canceller.commit()
        assert await asyncio.wait_for(pending, 10) is None
    assert await _count(state) == 0


async def test_a_claim_in_flight_serialises_a_later_cancel(one):
    """The other order: the claim wins, and the cancel does not corrupt the claim row."""
    state, c = one
    got = await ledger.claim(state.session_factory, c, tenant_id="default", now=NOW)
    assert got is not None
    with tenant_scope("default"):
        async with state.session_factory() as db:
            await db.execute(update(Event).where(Event.id == c.event_id).values(cancelled=True))
            await db.commit()
    assert await _count(state) == 1
