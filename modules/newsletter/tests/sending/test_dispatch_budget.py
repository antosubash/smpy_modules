"""The dispatcher tick (Task 7) and the shared send budget (review focus 4).

Never more than ``daily_limit`` counted attempts in any rolling 24 h, whoever
spends them (campaigns of any tenant, test sends, two ticks at once); the
oldest-started campaign goes first, and the rest continue the next day.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import finalize_session
from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.errors import TransportUnavailable
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import DispatchLock
from sm_newsletter.sending import deliver as delivering
from sm_newsletter.sending.dispatch import tick
from sqlalchemy import update

from tests.pg_support import USING_POSTGRES
from tests.support.campaign_world import campaign_row, send_rows
from tests.support.deliver_world import SECRET
from tests.support.dispatch_world import (
    DAY,
    busiest_day,
    counted_times,
    due,
    run_tick,
    sent_to,
    started,
    token_of,
    world,
)
from tests.support.fake_transport import FakeTransport
from tests.support.sending import NOW, T, send, used

pytestmark = pytest.mark.unbound_tenant


@pytest.fixture
async def built(tmp_path):
    """``build(**settings)``: the app and its state (disposed afterwards)."""
    made: list = []

    async def build(**settings):
        app, state, draft = await world(tmp_path, **settings)
        made.append((state, draft))
        return app, state

    yield build
    for state, _ in made:
        await state.engine.dispose()


async def test_daily_cap_rollover_two_days(built):
    app, state = await built(daily_limit=5, per_minute_limit=100)
    cid, emails = await due(state, 8)
    smtp = FakeTransport()

    first = await run_tick(app, state, smtp)
    assert (first.started, first.spent, first.stopped) == (1, 5, "budget")
    later = await run_tick(app, state, smtp, at=NOW + timedelta(hours=1))
    assert (later.spent, later.stopped) == (0, "budget")
    assert (await campaign_row(state, T, cid)).status == "sending"

    next_day = await run_tick(app, state, smtp, at=NOW + DAY + timedelta(seconds=1))
    assert (next_day.spent, next_day.finished) == (3, 1)
    assert (await campaign_row(state, T, cid)).status == "sent"
    assert sorted(sent_to(smtp)) == sorted(emails)
    assert busiest_day(await counted_times(state)) == 5


async def test_a_capped_day_neither_connects_nor_pauses_on_a_bad_login(built):
    """No budget left: the tick stops before the relay, so a capped day neither
    logs in every minute nor lets a refused login pause every campaign."""
    app, state = await built(daily_limit=2, per_minute_limit=100)
    cid, _ = await due(state, 4)
    assert (await run_tick(app, state, FakeTransport())).stopped == "budget"

    smtp = FakeTransport()
    capped = await run_tick(app, state, smtp, at=NOW + timedelta(hours=1))
    assert (capped.spent, capped.stopped, smtp.opened) == (0, "budget", 0)

    refused = FakeTransport(open_error=TransportUnavailable("auth: 535", stage="auth"))
    again = await run_tick(app, state, refused, at=NOW + timedelta(hours=2))
    assert (again.stopped, again.paused) == ("budget", 0)
    assert (await campaign_row(state, T, cid)).status == "sending"


async def test_per_minute_limit(built):
    app, state = await built(daily_limit=100, per_minute_limit=3)
    await due(state, 7)
    smtp = FakeTransport()

    assert (await run_tick(app, state, smtp)).spent == 3
    again = await run_tick(app, state, smtp)
    assert (again.spent, again.stopped) == (0, "budget")
    assert (await run_tick(app, state, smtp, at=NOW + timedelta(seconds=61))).spent == 3
    assert len(set(sent_to(smtp))) == 6


class _Clock:
    """A clock a send moves on by one second and a wait by what it waits."""

    def __init__(self, at: datetime) -> None:
        self.now = at

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    async def on_send(self, _message) -> None:
        self.now += timedelta(seconds=1)


async def test_a_full_minute_waits_instead_of_skipping_the_next_tick(built):
    """Beat ticks every 60 s, but a tick's sends land just after it starts: the
    next tick finds them still inside the minute and waits them out, rather
    than stopping (which would send only every other minute)."""
    app, state = await built(daily_limit=100, per_minute_limit=3)
    await due(state, 7)
    clock = _Clock(NOW)
    smtp = FakeTransport(on_send=clock.on_send)
    settings = app.state.sm_newsletter.settings

    async def at(when):
        clock.now = when
        return await tick(
            state.session_factory,
            settings=settings,
            secret=SECRET,
            transport=smtp,
            clock=clock,
            sleep=clock.sleep,
        )

    first, second = await at(NOW), await at(NOW + timedelta(seconds=60))
    assert (first.spent, first.stopped) == (3, "budget")
    assert (second.spent, second.stopped) == (3, "budget")
    times = await counted_times(state)
    assert max(sum(1 for t in times if s <= t <= s + timedelta(seconds=60)) for s in times) == 3


async def test_test_sends_share_the_budget(built):
    app, state = await built(daily_limit=5, per_minute_limit=100)
    await due(state, 3)
    with tenant_scope(T):
        await used(state, at=NOW - timedelta(hours=1), count=4)
    smtp = FakeTransport()

    summary = await run_tick(app, state, smtp)

    assert (summary.spent, summary.stopped) == (1, "budget")
    assert len(smtp.sent) == 1
    assert busiest_day(await counted_times(state)) == 5


async def test_oldest_started_first_across_tenants(built):
    app, state = await built(daily_limit=2, per_minute_limit=100)
    a, _ = await started(state, 2, tenant="a", at=datetime(2026, 11, 5, 10, 0, tzinfo=UTC))
    b, b_emails = await started(state, 2, tenant="b", at=datetime(2026, 11, 5, 9, 0, tzinfo=UTC))
    smtp = FakeTransport()

    summary = await run_tick(app, state, smtp)

    assert (summary.spent, summary.stopped) == (2, "budget")
    assert sorted(sent_to(smtp)) == sorted(b_emails)
    rows = {row.email: row for row in await send_rows(state, "b", b)}
    for message in smtp.sent:
        token = token_of(message)
        assert token is not None
        assert (token.tenant_id, token.campaign_id) == ("b", b)
        assert token.send_id == rows[message.to].id
    assert {row.status for row in await send_rows(state, "a", a)} == {"queued"}


async def test_concurrent_ticks_never_exceed_cap(built):
    app, state = await built(daily_limit=3, per_minute_limit=100)
    await due(state, 5)
    one, two = FakeTransport(), FakeTransport()

    await asyncio.gather(run_tick(app, state, one), run_tick(app, state, two))

    addresses = sent_to(one) + sent_to(two)
    assert len(addresses) == 3
    assert len(set(addresses)) == 3
    assert len(await counted_times(state)) == 3


# A4: the dispatcher's SQLite lease is taken over by a test send that spends
# the rest of the budget; the dispatcher's next reservation is fenced out.

sqlite_lease = pytest.mark.skipif(USING_POSTGRES, reason="the lease is the SQLite lock row's")


async def _take_over(app, state, draft: int, recipients: list[str]) -> None:
    """Expire the dispatcher's lease, then test send ``recipients`` (which
    takes the lock and spends the budget)."""
    table = DispatchLock.__table__  # ty: ignore[unresolved-attribute]
    async with state.session_factory() as db:
        await db.execute(update(table).values(locked_until=utcnow() - timedelta(seconds=1)))
        await finalize_session(db)
    results = await send(app, state, draft, recipients)
    assert [r.outcome for r in results] == ["accepted"] * len(recipients)


async def _takeover_world(tmp_path):
    app, state, draft = await world(tmp_path, daily_limit=3, per_minute_limit=100)
    cid, emails = await started(state, 5, at=NOW - timedelta(hours=1))
    return app, state, draft, cid, emails


@sqlite_lease
async def test_takeover_during_eligibility_never_over_budget(tmp_path, monkeypatch):
    app, state, draft, cid, _ = await _takeover_world(tmp_path)
    real = delivering.subscribers_by_uuid
    done = False

    async def taken_over(session, **kw):
        nonlocal done
        hits = await real(session, **kw)
        if not done:
            done = True
            await _take_over(
                app, state, draft, ["t0@example.org", "t1@example.org", "t2@example.org"]
            )
        return hits

    monkeypatch.setattr(delivering, "subscribers_by_uuid", taken_over)
    smtp = FakeTransport()
    try:
        summary = await run_tick(app, state, smtp)

        assert (summary.stopped, summary.spent) == ("busy", 0)
        assert smtp.sent == []
        assert {row.status for row in await send_rows(state, T, cid)} == {"queued"}
        assert len(await counted_times(state)) == 3
    finally:
        await state.engine.dispose()


@sqlite_lease
async def test_takeover_during_smtp_never_over_budget(tmp_path):
    app, state, draft, cid, emails = await _takeover_world(tmp_path)

    async def taken_over(_message) -> None:
        if len(smtp.sent) == 1:
            await _take_over(app, state, draft, ["t0@example.org", "t1@example.org"])

    smtp = FakeTransport(on_send=taken_over)
    try:
        summary = await run_tick(app, state, smtp)

        assert (summary.stopped, summary.spent) == ("busy", 1)
        assert sent_to(smtp) == [emails[0]]
        statuses = [row.status for row in await send_rows(state, T, cid)]
        assert statuses == ["sent", "queued", "queued", "queued", "queued"]
        assert len(await counted_times(state)) == 3
    finally:
        await state.engine.dispose()
