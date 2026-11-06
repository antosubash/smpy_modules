"""The dispatcher tick (Task 7): how a slice and a tick end, besides the budget.

A list that is gone pauses only its own campaign, a slice gives the lock back
after :data:`MAX_SLICE_STEPS` recipients however many were skipped, and the
deadline ends a tick before any recipient.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns.lifecycle import split_paused
from sm_newsletter.core.suppression import suppress
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.sending import dispatch as dispatching
from sm_newsletter.sending.dispatch import MAX_SLICE_STEPS

from tests.support.campaign_world import campaign_row, send_rows
from tests.support.dispatch_world import due, run_tick, sent_to, started, world
from tests.support.fake_transport import FakeTransport
from tests.support.records_seed import set_list_kind
from tests.support.sending import T

pytestmark = pytest.mark.unbound_tenant

NINE, TEN = (datetime(2026, 11, 5, h, 0, tzinfo=UTC) for h in (9, 10))


@pytest.fixture
async def built(tmp_path):
    app, state, _ = await world(tmp_path, daily_limit=100, per_minute_limit=100)
    yield app, state
    await state.engine.dispose()


async def test_list_gone_pauses_only_its_campaign(built):
    app, state = built
    gone, _ = await started(state, 1, at=NINE)
    other, other_emails = await started(state, 1, tenant="b", at=TEN)
    await set_list_kind(state, T, "news", "form")
    smtp = FakeTransport()

    summary = await run_tick(app, state, smtp)

    campaign = await campaign_row(state, T, gone)
    assert campaign.status == "paused"
    assert split_paused(campaign.paused_reason)[0] == "list_unavailable"
    assert sent_to(smtp) == other_emails
    assert (summary.paused, summary.spent, summary.stopped) == (1, 1, "idle")
    assert (await campaign_row(state, "b", other)).status == "sent"


async def test_slice_releases_the_lock_after_max_steps(built, monkeypatch):
    app, state = built
    cid, emails = await started(state, MAX_SLICE_STEPS + 4, at=NINE)
    kept = emails[:2]
    with tenant_scope(T):
        async with state.session_factory() as db:
            for email in emails[2:]:
                await suppress(db, tenant_id=T, email=email, reason="complaint", source="admin")
            await finalize_session(db)
    steps: list[int] = []  # recipients handled per lock acquisition
    real_lock, real_deliver = dispatching.dispatch_lock, dispatching.deliver_one

    @asynccontextmanager
    async def counted_lock(*args, **kw):
        async with real_lock(*args, **kw) as lock:
            steps.append(0)
            yield lock

    async def counted_deliver(*args, **kw):
        steps[-1] += 1
        return await real_deliver(*args, **kw)

    monkeypatch.setattr(dispatching, "dispatch_lock", counted_lock)
    monkeypatch.setattr(dispatching, "deliver_one", counted_deliver)
    smtp = FakeTransport()

    summary = await run_tick(app, state, smtp)

    assert len(steps) >= 2 and max(steps) <= MAX_SLICE_STEPS
    assert (summary.spent, summary.skipped) == (2, MAX_SLICE_STEPS + 2)
    assert sorted(sent_to(smtp)) == sorted(kept)
    statuses = [row.status for row in await send_rows(state, T, cid)]
    assert statuses.count("suppressed") == MAX_SLICE_STEPS + 2


async def test_deadline_ends_the_tick(built):
    app, state = built
    cid, _ = await due(state, 2)
    smtp = FakeTransport()

    summary = await run_tick(app, state, smtp, deadline_s=0)

    assert (summary.started, summary.spent, summary.stopped) == (1, 0, "deadline")
    assert smtp.sent == []
    assert {row.status for row in await send_rows(state, T, cid)} == {"queued"}
