"""Sending under budgets: claim first, one failure never blocks the rest, nothing is retried."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest
from simple_module_core.mail import MailMessage
from simple_module_core.resources import ResourcePrincipal
from sm_events.core.tenancy import tenant_scope
from sm_events.models import ReminderSent
from sm_events.reminders import limits, send
from sm_events.reminders.candidates import Candidate
from sm_events.reminders.recipients import Eligibility
from sm_events.reminders.runtime import Recipient
from sqlalchemy import select

NOW = datetime(2026, 7, 1, 9, tzinfo=UTC)
START = datetime(2026, 7, 1, 10, tzinfo=UTC)
ADDRESS_FRAGMENT = "private.person@example.org"


class Crash(BaseException):
    pass


class Sender:
    delivers_email = True

    def __init__(self, behaviour=None, delay=0.0):
        self.sent: list[MailMessage] = []
        self.behaviour, self.delay = behaviour, delay

    async def send(self, message: MailMessage) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.behaviour is not None:
            self.behaviour(message, len(self.sent))
        self.sent.append(message)


def raises(exc):
    def behaviour(message, n):
        raise exc

    return behaviour


def _candidates(event_id, revision, n=1, lead=60):
    return [
        Candidate(
            event_id, revision, str(event_id), START, START + timedelta(hours=1), lead,
            f"user{i:03d}", "en",
        )
        for i in range(n)
    ]  # fmt: skip


def _eligible(event_id, cands):
    out = Eligibility()
    for c in cands:
        who = Recipient(
            c.user_id,
            f"{c.user_id}@example.org",
            ResourcePrincipal(user_id=c.user_id, permissions=frozenset()),
        )
        out.allowed[c.user_id] = (who, {event_id})
    return out


async def _render(c, who):
    return MailMessage(to=who.email, subject=f"Reminder for {c.user_id}", text="body")


def _budget(**kw):
    base = {"remaining": 300, "tenant_remaining": 100, "deadline": time.monotonic() + 60}
    base.update(kw)
    return send.Budget(**base)


async def _run(state, cands, sender, *, eligible=None, budget=None, render=_render, event_id=None):
    event_id = event_id or cands[0].event_id
    return await send.send_tenant(
        state.session_factory,
        tenant_id="default",
        candidates=cands,
        eligible=eligible or _eligible(event_id, cands),
        sender=sender,
        budget=budget or _budget(),
        render=render,
        now=NOW,
    )


async def _rows(state):
    with tenant_scope("default"):
        async with state.session_factory() as db:
            return list(
                (
                    await db.execute(select(ReminderSent).order_by(ReminderSent.recipient_id))
                ).scalars()
            )


async def test_sent_and_marked(cast):
    state, eid, rev = cast
    sender = Sender()
    counts = await _run(state, _candidates(eid, rev), sender)
    assert (counts.sent, counts.failed, counts.denied, counts.taken, counts.deferred) == (
        1,
        0,
        0,
        0,
        0,
    )
    assert [m.to for m in sender.sent] == ["user000@example.org"]
    (row,) = await _rows(state)
    assert (row.state, row.code, row.sent_at is not None) == ("sent", None, True)


async def test_the_claim_is_committed_before_the_send(cast):
    state, eid, rev = cast
    seen = []

    async def watcher(message, n):
        pass

    class Peek(Sender):
        async def send(self, message):
            seen.append([r.state for r in await _rows(state)])
            await super().send(message)

    await _run(state, _candidates(eid, rev), Peek())
    assert seen == [["sending"]]  # durable, and already past ``claimed``, before the transport ran


async def test_failure_marks_failed_no_retry(cast):
    state, eid, rev = cast
    cands = _candidates(eid, rev)
    counts = await _run(state, cands, Sender(raises(RuntimeError("boom"))))
    assert (counts.sent, counts.failed) == (0, 1)
    (row,) = await _rows(state)
    assert (row.state, row.code) == ("failed", "send_failed")
    again = Sender()
    counts = await _run(state, cands, again)
    assert (counts.taken, counts.sent, again.sent) == (1, 0, [])  # never retried


async def test_timeout_code(cast, monkeypatch):
    state, eid, rev = cast
    monkeypatch.setattr(limits, "REMINDER_SEND_TIMEOUT", timedelta(milliseconds=100))
    counts = await _run(state, _candidates(eid, rev), Sender(delay=2))
    assert counts.failed == 1
    (row,) = await _rows(state)
    assert (row.state, row.code) == ("failed", "send_timeout")


async def test_outage_breaker(cast):
    state, eid, rev = cast
    counts = await _run(state, _candidates(eid, rev, 50), Sender(raises(OSError("down"))))
    assert (counts.failed, counts.deferred, counts.sent) == (3, 47, 0)
    assert len(await _rows(state)) == 3  # the deferred ones claimed nothing


async def test_one_failure_does_not_block_the_rest(cast):
    state, eid, rev = cast

    def flaky(message, n):
        if message.to == "user001@example.org":
            raise OSError("one bad apple")

    sender = Sender(flaky)
    counts = await _run(state, _candidates(eid, rev, 6), sender)
    assert (counts.sent, counts.failed, counts.deferred) == (5, 1, 0)
    states = {r.recipient_id: r.state for r in await _rows(state)}
    assert states["user001"] == "failed" and set(states.values()) == {"sent", "failed"}


async def test_wall_clock_budget(cast):
    state, eid, rev = cast
    sender = Sender(delay=0.3)
    budget = _budget(deadline=time.monotonic() + 1.0)
    counts = await _run(state, _candidates(eid, rev, 20), sender, budget=budget)
    assert 2 <= counts.sent <= 5
    assert counts.sent + counts.deferred == 20
    assert len(await _rows(state)) == counts.sent  # nothing claimed past the deadline


async def test_send_budget_per_tenant_and_install_wide(cast):
    state, eid, rev = cast
    budget = _budget(remaining=7, tenant_remaining=5)
    first = await _run(state, _candidates(eid, rev, 10), Sender(), budget=budget)
    assert (first.sent, first.deferred) == (5, 5)
    budget.tenant_remaining = 5  # the next tenant's allowance
    second = await _run(state, _candidates(eid, rev, 10)[5:], Sender(), budget=budget)
    assert (second.sent, second.deferred) == (2, 3)  # the install-wide budget ran out first
    assert budget.remaining == 0


async def test_crash_after_claim_is_unfinished_never_duplicated(cast):
    state, eid, rev = cast
    cands = _candidates(eid, rev)
    with pytest.raises(Crash):
        await _run(state, cands, Sender(raises(Crash())))
    (row,) = await _rows(state)
    assert row.state == "sending"
    again = Sender()
    counts = await _run(state, cands, again)
    assert (counts.taken, again.sent) == (1, [])
    assert [r.state for r in await _rows(state)] == ["sending"]  # lost, not repeated


async def test_a_render_failure_burns_no_claim(cast):
    state, eid, rev = cast

    async def broken(c, who):
        raise ValueError("template bug")

    cands = _candidates(eid, rev)
    counts = await _run(state, cands, Sender(), render=broken)
    assert (counts.failed, counts.sent) == (1, 0)
    assert await _rows(state) == []
    ok = await _run(state, cands, Sender())  # the next tick, fixed: it still goes out
    assert ok.sent == 1


async def test_a_render_that_finds_nothing_to_show_is_denied(cast):
    state, eid, rev = cast

    async def nothing(c, who):
        return None

    counts = await _run(state, _candidates(eid, rev), Sender(), render=nothing)
    assert (counts.denied, counts.sent) == (1, 0) and await _rows(state) == []


async def test_denied_candidates_cost_nothing(cast):
    state, eid, rev = cast
    cands = _candidates(eid, rev, 3)
    elig = _eligible(eid, cands[:1])
    elig.allowed["user000"] = (elig.allowed["user000"][0], set())  # may see none of the events
    budget = _budget(remaining=1)
    counts = await _run(state, cands, Sender(), eligible=elig, budget=budget)
    assert (counts.denied, counts.sent) == (3, 0) and budget.remaining == 1
    assert await _rows(state) == []
