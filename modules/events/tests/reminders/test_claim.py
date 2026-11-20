"""At most once: the claim is committed before any send, and every transition is conditional."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sm_events.core.constants import reminders_limits as limits
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Event, ReminderSent
from sm_events.reminders import claim as ledger
from sm_events.reminders.candidates import Candidate
from sqlalchemy import select, update

from tests.reminders.support import published, world

NOW = datetime(2026, 7, 1, 9, tzinfo=UTC)
START = datetime(2026, 7, 1, 10, tzinfo=UTC)
LEASE = limits.REMINDER_CLAIM_LEASE


@pytest.fixture
async def one(db_state):
    """A published event and the candidate for one of its followers, committed."""
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


async def _rows(state) -> list[ReminderSent]:
    with tenant_scope("default"):
        async with state.session_factory() as db:
            return list(
                (await db.execute(select(ReminderSent).order_by(ReminderSent.id))).scalars()
            )


async def _edit(state, event_id, **values):
    with tenant_scope("default"):
        async with state.session_factory() as db:
            await db.execute(update(Event).where(Event.id == event_id).values(**values))
            await db.commit()


async def test_claim_once(one):
    state, c = one
    first = await ledger.claim(state.session_factory, c, tenant_id="default", now=NOW)
    assert first is not None and first.claimed_at == NOW
    assert await ledger.claim(state.session_factory, c, tenant_id="default", now=NOW) is None
    (row,) = await _rows(state)
    assert (row.id, row.state, row.claimed_at, row.sent_at, row.code) == (
        first.id, "claimed", NOW, None, None
    )  # fmt: skip
    assert (row.event_id, row.occurrence_key, row.starts_at) == (
        c.event_id,
        c.occurrence_key,
        START,
    )
    assert (row.recipient_id, row.lead_minutes, row.tenant_id) == ("u", 60, "default")


async def test_claim_commits_before_return(one):
    """A session that opens afterwards sees it: nothing is pending in the claimer's own."""
    state, c = one
    await ledger.claim(state.session_factory, c, tenant_id="default", now=NOW)
    assert [r.state for r in await _rows(state)] == ["claimed"]


async def test_each_recipient_lead_and_start_is_its_own_claim(one):
    state, c = one
    factory = state.session_factory
    for other in (
        replace(c, user_id="w"),
        replace(c, lead=15),
        replace(c, start=START + timedelta(hours=1), end=START + timedelta(hours=2)),
    ):
        assert await ledger.claim(factory, other, tenant_id="default", now=NOW) is not None
    assert await ledger.claim(factory, c, tenant_id="default", now=NOW) is not None
    assert len(await _rows(state)) == 4


async def test_moved_override_one_reminder(one):
    """A moved occurrence is claimed at its new start under its original key, once."""
    state, c = one
    moved = replace(c, occurrence_key=f"{c.event_id}:20260708T100000Z", start=START)
    assert await ledger.claim(state.session_factory, moved, tenant_id="default", now=NOW)
    assert await ledger.claim(state.session_factory, moved, tenant_id="default", now=NOW) is None


async def test_move_back_sends_nothing(one):
    state, c = one
    s2 = replace(c, start=START + timedelta(days=1), end=START + timedelta(days=1, hours=1))
    factory = state.session_factory
    assert await ledger.claim(factory, c, tenant_id="default", now=NOW) is not None
    assert await ledger.claim(factory, s2, tenant_id="default", now=NOW) is not None
    assert await ledger.claim(factory, c, tenant_id="default", now=NOW) is None  # back at S1


@pytest.mark.parametrize("change", ["revision", "unpublish", "cancelled", "trashed"])
async def test_guard_refuses_changed_event(one, change):
    state, c = one
    values = {
        "revision": {"revision": c.revision + 1},
        "unpublish": {"status": "draft"},
        "cancelled": {"cancelled": True},
        "trashed": {"is_deleted": True},
    }[change]
    await _edit(state, c.event_id, **values)
    assert await ledger.claim(state.session_factory, c, tenant_id="default", now=NOW) is None
    assert await _rows(state) == []


async def test_a_republished_event_is_claimable_again(one):
    """Unpublished, then republished (a new revision): the next tick's candidate carries the
    new revision and claims normally; the old one was refused and wrote nothing."""
    state, c = one
    await _edit(state, c.event_id, status="draft", revision=c.revision + 1)
    assert await ledger.claim(state.session_factory, c, tenant_id="default", now=NOW) is None
    await _edit(state, c.event_id, status="published", revision=c.revision + 2)
    fresh = replace(c, revision=c.revision + 2)
    assert await ledger.claim(state.session_factory, fresh, tenant_id="default", now=NOW)


@pytest.mark.unbound_tenant
async def test_another_tenants_event_is_not_claimable(one):
    state, c = one
    assert await ledger.claim(state.session_factory, c, tenant_id="other", now=NOW) is None
    assert await _rows(state) == []


# --- the state machine: claimed -> sending -> sent | failed; claimed -> claimed (reclaim) ------


async def test_claimed_to_sending_to_sent(one):
    state, c = one
    f = state.session_factory
    got = await ledger.claim(f, c, tenant_id="default", now=NOW)
    assert await ledger.begin_send(f, "default", got) is True
    assert [r.state for r in await _rows(state)] == ["sending"]
    assert await ledger.mark_sent(f, "default", got.id, now=NOW + timedelta(seconds=1)) is True
    (row,) = await _rows(state)
    assert (row.state, row.sent_at, row.code) == ("sent", NOW + timedelta(seconds=1), None)


async def test_sending_to_failed(one):
    state, c = one
    f = state.session_factory
    got = await ledger.claim(f, c, tenant_id="default", now=NOW)
    await ledger.begin_send(f, "default", got)
    assert await ledger.mark_failed(f, "default", got.id, "send_failed") is True
    (row,) = await _rows(state)
    assert (row.state, row.code, row.sent_at) == ("failed", "send_failed", None)


async def test_every_other_transition_is_refused(one):
    state, c = one
    f = state.session_factory
    got = await ledger.claim(f, c, tenant_id="default", now=NOW)
    # claimed: cannot be marked sent or failed without going through sending
    assert await ledger.mark_sent(f, "default", got.id, now=NOW) is False
    assert await ledger.mark_failed(f, "default", got.id, "send_failed") is False
    assert await ledger.begin_send(f, "default", got) is True
    assert await ledger.begin_send(f, "default", got) is False  # not twice
    assert await ledger.mark_sent(f, "default", got.id, now=NOW) is True
    # sent is final
    assert await ledger.mark_sent(f, "default", got.id, now=NOW) is False
    assert await ledger.mark_failed(f, "default", got.id, "send_failed") is False
    assert [r.state for r in await _rows(state)] == ["sent"]


async def test_a_failed_row_is_final(one):
    state, c = one
    f = state.session_factory
    got = await ledger.claim(f, c, tenant_id="default", now=NOW)
    await ledger.begin_send(f, "default", got)
    await ledger.mark_failed(f, "default", got.id, "send_timeout")
    assert await ledger.mark_sent(f, "default", got.id, now=NOW) is False
    later = NOW + 10 * LEASE
    assert await ledger.claim(f, c, tenant_id="default", now=later) is None
    assert [r.state for r in await _rows(state)] == ["failed"]


@pytest.mark.unbound_tenant
async def test_marks_never_cross_tenants(one):
    state, c = one
    f = state.session_factory
    got = await ledger.claim(f, c, tenant_id="default", now=NOW)
    assert await ledger.begin_send(f, "other", got) is False
    await ledger.begin_send(f, "default", got)
    assert await ledger.mark_sent(f, "other", got.id, now=NOW) is False
    assert await ledger.mark_failed(f, "other", got.id, "send_failed") is False
    assert [r.state for r in await _rows(state)] == ["sending"]


async def test_a_live_lease_is_not_reclaimed(one):
    state, c = one
    f = state.session_factory
    await ledger.claim(f, c, tenant_id="default", now=NOW)
    inside = NOW + LEASE - timedelta(seconds=1)
    assert await ledger.claim(f, c, tenant_id="default", now=inside) is None


async def test_an_expired_claim_that_never_began_sending_is_reclaimed(one):
    """A crash between the claim and the transport call provably sent nothing."""
    state, c = one
    f = state.session_factory
    first = await ledger.claim(f, c, tenant_id="default", now=NOW)
    later = NOW + LEASE + timedelta(seconds=1)
    second = await ledger.claim(f, c, tenant_id="default", now=later)
    assert second is not None and second.id == first.id and second.claimed_at == later
    # The slow first holder lost it: it must not send.
    assert await ledger.begin_send(f, "default", first) is False
    assert await ledger.begin_send(f, "default", second) is True
    assert [r.state for r in await _rows(state)] == ["sending"]
    # ... and the lease is a fresh one for the new holder.
    assert await ledger.claim(f, c, tenant_id="default", now=later + timedelta(seconds=1)) is None


async def test_a_row_that_began_sending_is_never_reclaimed(one):
    """A crash after ``sending`` may have sent: at most once means that reminder is lost, and a
    duplicate is the thing never allowed."""
    state, c = one
    f = state.session_factory
    got = await ledger.claim(f, c, tenant_id="default", now=NOW)
    await ledger.begin_send(f, "default", got)
    forever = NOW + 365 * timedelta(days=1)
    assert await ledger.claim(f, c, tenant_id="default", now=forever) is None
    assert [r.state for r in await _rows(state)] == ["sending"]


async def test_reclaim_is_refused_when_the_event_changed(one):
    state, c = one
    f = state.session_factory
    await ledger.claim(f, c, tenant_id="default", now=NOW)
    await _edit(state, c.event_id, cancelled=True)
    assert await ledger.claim(f, c, tenant_id="default", now=NOW + 2 * LEASE) is None
    (row,) = await _rows(state)
    assert row.claimed_at == NOW  # untouched
