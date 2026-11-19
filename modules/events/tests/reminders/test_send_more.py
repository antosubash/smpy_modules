"""Sending, part two: the lease, the log and two workers."""

from __future__ import annotations

import asyncio
import logging

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.reminders import send

from tests.pg_support import USING_POSTGRES
from tests.reminders.test_send import (
    ADDRESS_FRAGMENT,
    Sender,
    _candidates,
    _rows,
    _run,
    raises,
)


async def test_a_lost_lease_sends_nothing(cast, monkeypatch):
    state, eid, rev = cast

    async def lost(factory, tenant_id, held):
        return False

    monkeypatch.setattr(send.ledger, "begin_send", lost)
    sender = Sender()
    counts = await _run(state, _candidates(eid, rev), sender)
    assert (counts.taken, counts.sent, sender.sent) == (1, 0, [])


async def test_failure_log_has_no_address(cast, caplog):
    state, eid, rev = cast
    secret = Sender(
        raises(RuntimeError(f"550 no such user {ADDRESS_FRAGMENT} (Subject: Reminder for user000)"))
    )
    with caplog.at_level(logging.DEBUG):
        await _run(state, _candidates(eid, rev), secret)
        await _run(state, _candidates(eid, rev, 1), Sender(raises(TimeoutError(ADDRESS_FRAGMENT))))
    text = " ".join(f"{r.getMessage()} {r.args}" for r in caplog.records)
    assert "RuntimeError" in text
    for forbidden in (ADDRESS_FRAGMENT, "@example.org", "Reminder for", "no such user"):
        assert forbidden not in text, forbidden


@pytest.mark.skipif(not USING_POSTGRES, reason="two real workers")
async def test_two_workers_send_each_reminder_once(cast):
    state, eid, rev = cast
    cands = _candidates(eid, rev, 20)
    first, second = Sender(delay=0.02), Sender(delay=0.02)
    with tenant_scope("default"):
        await asyncio.gather(_run(state, cands, first), _run(state, cands, second))
    got = sorted(m.to for m in first.sent + second.sent)
    assert got == sorted(f"{c.user_id}@example.org" for c in cands)  # each exactly once
    assert {r.state for r in await _rows(state)} == {"sent"}
