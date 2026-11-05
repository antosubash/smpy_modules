"""``send_test`` against the transports: SMTP, a relay that is down, two
concurrent sends, a lost lock lease and per-row timestamps."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime

import pytest
from sm_newsletter.campaigns import test_send
from sm_newsletter.core.errors import DispatchBusy, SendBudgetExhausted, TransportUnavailable
from sm_newsletter.sending import ledger, lock
from sm_newsletter.sending.transport import console

from tests.support.sending import NOW, T, attempt_rows, make_app, send


async def test_transport_down_502_no_rows():
    app, state, cid = await make_app(transport="smtp", smtp_host="127.0.0.1", smtp_port=1)
    try:
        with pytest.raises(TransportUnavailable) as err:
            await send(app, state, cid, ["a@example.org"])
        assert (err.value.status, err.value.code) == (502, "transport_unavailable")
        assert await ledger.attempts_since(state.session_factory, since=NOW) == 0
        assert await attempt_rows(state) == []
    finally:
        await state.engine.dispose()


async def test_smtp_path_via_aiosmtpd(relay, make_transport, monkeypatch):
    _, recorder = relay
    monkeypatch.setattr(test_send, "transport_for", lambda settings: make_transport())
    app, state, cid = await make_app(transport="smtp")
    try:
        results = await send(app, state, cid, ["ok@example.org", "bounce@example.org"])
        assert [(r.recipient, r.outcome, r.code) for r in results] == [
            ("ok@example.org", "accepted", 250),
            ("bounce@example.org", "rejected", 550),
        ]
        assert [r.outcome for r in await attempt_rows(state)] == ["accepted", "rejected"]
        (delivered,) = recorder.delivered
        assert b"Subject: [TEST] Hello" in delivered.original_content
        assert b"List-Unsubscribe: <https://news.example.org/newsletter/u/test>" in (
            delivered.original_content
        )
    finally:
        await state.engine.dispose()


async def test_concurrent_test_sends_never_exceed_the_cap(tmp_path):
    """Two sends of two under a cap of three: the lock serialises admission."""
    app, state, cid = await make_app(daily_limit=3, file=tmp_path / "race.db")
    try:
        pair = (["a@example.org", "b@example.org"], ["c@example.org", "d@example.org"])
        outcomes = await asyncio.gather(
            *(send(app, state, cid, rs) for rs in pair), return_exceptions=True
        )
        refused = [o for o in outcomes if isinstance(o, SendBudgetExhausted)]
        sent = [o for o in outcomes if isinstance(o, list)]
        assert (len(refused), len(sent)) == (1, 1), outcomes
        assert await ledger.attempts_since(state.session_factory, since=NOW) == 2
        assert len(console.captured(T)) == 2
    finally:
        await state.engine.dispose()


async def test_rows_stamped_at_their_own_send_without_a_clock(built):
    app, state, cid = built
    start = datetime.now(UTC)
    async with state.session_factory() as db:
        await test_send.send_test(
            app, db, tenant_id=T, campaign_id=cid, recipients=["a@x.org", "b@x.org"], roles=[]
        )
    stamps = [r.attempted_at for r in await attempt_rows(state)]
    assert start <= stamps[0] <= stamps[1] <= datetime.now(UTC)


async def test_lost_lease_stops_the_rest(built, monkeypatch):
    """The lock's ``renew`` reports a takeover before the second recipient."""
    app, state, cid = built
    real = test_send.dispatch_lock

    @contextlib.asynccontextmanager
    async def losing(*args, **kwargs):
        async with real(*args, **kwargs):
            calls = iter([None])

            async def renew() -> None:
                if next(calls, "lost") == "lost":
                    raise DispatchBusy()

            yield lock.HeldLock(renew)

    monkeypatch.setattr(test_send, "dispatch_lock", losing)
    results = await send(app, state, cid, ["a@x.org", "b@x.org", "c@x.org"])
    assert [(r.recipient, r.outcome, r.detail) for r in results][1:] == [
        ("b@x.org", "failed", "dispatch_busy"),
        ("c@x.org", "failed", "dispatch_busy"),
    ]
    assert results[0].outcome == "accepted"
    assert [r.recipient for r in await attempt_rows(state)] == ["a@x.org"]
    assert [m.to for m in console.captured(T)] == ["a@x.org"]
