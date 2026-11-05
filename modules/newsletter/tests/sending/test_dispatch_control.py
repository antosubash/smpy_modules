"""The dispatcher tick (Task 7): what stops it, what it recovers and finishes,
and pause or cancel pressed mid-slice (review focus 1, 2 and 5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns import lifecycle
from sm_newsletter.campaigns.lifecycle import split_paused
from sm_newsletter.core.errors import TransportUnavailable
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import SendAttempt
from sm_newsletter.sending.ledger import attempts_since
from sm_newsletter.sending.lock import dispatch_lock
from sm_newsletter.sending.transport import DeliveryResult

from tests.support.campaign_world import campaign_row, send_rows
from tests.support.deliver_world import attempts, is_suppressed
from tests.support.dispatch_world import (
    DAY,
    due,
    lifecycle_action,
    run_tick,
    sent_to,
    started,
    world,
)
from tests.support.fake_transport import FakeTransport
from tests.support.sending import NOW, T

pytestmark = pytest.mark.unbound_tenant

NINE, TEN = (datetime(2026, 11, 5, h, 0, tzinfo=UTC) for h in (9, 10))


@pytest.fixture
async def built(tmp_path):
    app, state, _ = await world(tmp_path, daily_limit=100, per_minute_limit=100)
    yield app, state
    await state.engine.dispose()


async def _in_flight(state, cid, *, lease_until) -> tuple[int, str]:
    """The campaign's first row claimed (``sending``) with a ``pending`` attempt,
    as a sender that stopped after the relay's 250 leaves it."""
    row = (await send_rows(state, T, cid))[0]
    with tenant_scope(T):
        async with state.session_factory() as db:
            send = await db.merge(row)
            send.status, send.lease_until = "sending", lease_until
            db.add(
                SendAttempt(
                    campaign_id=cid,
                    send_id=row.id,
                    kind="campaign",
                    recipient=row.email,
                    attempted_at=NOW - timedelta(minutes=11),
                    outcome="pending",
                )
            )
            await finalize_session(db)
    return row.id, row.email


async def test_crash_between_accept_and_commit_never_resends(built):
    app, state = built
    cid, _ = await started(state, 2, at=NINE)
    send_id, email = await _in_flight(state, cid, lease_until=NOW - timedelta(seconds=1))
    smtp = FakeTransport()

    summary = await run_tick(app, state, smtp)

    assert summary.recovered == 1
    row = next(r for r in await send_rows(state, T, cid) if r.id == send_id)
    assert (row.status, row.error_kind, row.lease_until) == ("failed", "outcome_unknown", None)
    assert email not in sent_to(smtp) and len(smtp.sent) == 1
    pending = [a for a in await attempts(state) if a.send_id == send_id]
    assert [a.outcome for a in pending] == ["unknown"]
    assert await attempts_since(state.session_factory, since=NOW - DAY) == 2
    campaign = await campaign_row(state, T, cid)
    assert (campaign.status, campaign.failed_count, campaign.sent_count) == ("sent", 1, 1)


async def test_unexpired_lease_left_alone(built):
    app, state = built
    cid, _ = await started(state, 2, at=NINE)
    send_id, email = await _in_flight(state, cid, lease_until=NOW + timedelta(minutes=5))
    smtp = FakeTransport()

    summary = await run_tick(app, state, smtp)

    assert (summary.recovered, summary.finished) == (0, 0)
    row = next(r for r in await send_rows(state, T, cid) if r.id == send_id)
    assert row.status == "sending"
    assert [a.outcome for a in await attempts(state) if a.send_id == send_id] == ["pending"]
    assert email not in sent_to(smtp)
    assert (await campaign_row(state, T, cid)).status == "sending"


async def test_relay_quota_reply_stops_tick(built):
    app, state = built
    cid, emails = await started(state, 2, at=NINE)
    quota = DeliveryResult("rejected", 421, "4.7.0 Try again later", "rcpt")
    smtp = FakeTransport({emails[0]: quota})

    summary = await run_tick(app, state, smtp)

    assert (summary.spent, summary.stopped) == (1, "relay")
    assert sent_to(smtp) == [emails[0]]
    first = (await send_rows(state, T, cid))[0]
    assert (first.status, first.attempts) == ("queued", 1)
    assert first.retry_at is not None and first.retry_at.replace(tzinfo=UTC) > NOW
    assert (await campaign_row(state, T, cid)).status == "sending"


async def test_pause_class_pauses_and_stops(built):
    app, state = built
    cid, emails = await started(state, 2, at=NINE)
    other, other_emails = await started(state, 1, tenant="b", at=TEN)
    smtp = FakeTransport({emails[0]: DeliveryResult("rejected", 554, "5.4.5 Quota", "data")})

    summary = await run_tick(app, state, smtp)

    assert (summary.spent, summary.paused, summary.stopped) == (1, 1, "relay")
    assert sent_to(smtp) == [emails[0]]
    campaign = await campaign_row(state, T, cid)
    assert campaign.status == "paused"
    assert split_paused(campaign.paused_reason) == ("smtp_rejected", "554 5.4.5 Quota")
    assert {row.status for row in await send_rows(state, T, cid)} == {"queued"}
    assert not await is_suppressed(state, emails[0])
    assert {row.status for row in await send_rows(state, "b", other)} == {"queued"}

    await run_tick(app, state, smtp)
    assert sent_to(smtp) == [emails[0], *other_emails]
    assert (await campaign_row(state, "b", other)).status == "sent"


async def _untouched(state, campaigns) -> None:
    for tenant, cid in campaigns:
        assert {row.status for row in await send_rows(state, tenant, cid)} == {"queued"}
        assert await attempts(state, tenant) == []


async def test_auth_failure_at_open_pauses_all_sending(built):
    app, state = built
    campaigns = [(T, (await started(state, 1, at=NINE))[0])]
    campaigns.append(("b", (await started(state, 1, tenant="b", at=TEN))[0]))
    refused = TransportUnavailable("auth: 535 Authentication failed", stage="auth")
    smtp = FakeTransport(open_error=refused)

    summary = await run_tick(app, state, smtp)

    assert (summary.paused, summary.stopped, summary.spent) == (2, "relay", 0)
    for tenant, cid in campaigns:
        campaign = await campaign_row(state, tenant, cid)
        assert campaign.status == "paused"
        assert split_paused(campaign.paused_reason)[0] == "smtp_auth"
    await _untouched(state, campaigns)


async def test_connect_failure_changes_nothing(built):
    app, state = built
    cid, _ = await started(state, 1, at=NINE)
    before = await campaign_row(state, T, cid)
    smtp = FakeTransport(open_error=TransportUnavailable("connect: refused", stage="connect"))

    summary = await run_tick(app, state, smtp)

    assert (summary.stopped, summary.paused) == ("transport_unavailable", 0)
    after = await campaign_row(state, T, cid)
    assert (after.status, after.revision) == ("sending", before.revision)
    await _untouched(state, [(T, cid)])


async def test_finishes_campaign_when_done(built):
    app, state = built
    cid, emails = await started(state, 2, at=NINE)
    soft = DeliveryResult("rejected", 451, "4.3.0 Try later", "data")
    smtp = FakeTransport({emails[0]: soft})

    first = await run_tick(app, state, smtp)
    assert (first.spent, first.finished) == (2, 0)
    assert (await campaign_row(state, T, cid)).status == "sending"  # a retry is pending

    accepted = FakeTransport()
    second = await run_tick(app, state, accepted, at=NOW + timedelta(minutes=6))
    assert (second.spent, second.finished) == (1, 1)
    campaign = await campaign_row(state, T, cid)
    assert (campaign.status, campaign.sent_count) == ("sent", 2)
    assert campaign.finished_at is not None


async def test_cancel_mid_tick(built):
    app, state = built
    cid, _ = await started(state, 3, at=NINE)

    async def cancel_once(_message) -> None:
        if len(smtp.sent) == 1:
            await lifecycle_action(state, lifecycle.cancel, cid)

    smtp = FakeTransport(on_send=cancel_once)

    await run_tick(app, state, smtp)

    assert len(smtp.sent) == 1
    statuses = [row.status for row in await send_rows(state, T, cid)]
    assert statuses == ["sent", "cancelled", "cancelled"]
    assert (await campaign_row(state, T, cid)).status == "cancelled"


async def test_pause_resume_continues_without_duplicates(built):
    app, state = built
    cid, emails = await started(state, 4, at=NINE)

    async def pause_at_two(_message) -> None:
        if len(smtp.sent) == 2:
            await lifecycle_action(state, lifecycle.pause, cid)

    smtp = FakeTransport(on_send=pause_at_two)

    assert (await run_tick(app, state, smtp)).spent == 2
    assert (await run_tick(app, state, smtp)).spent == 0
    assert len(smtp.sent) == 2

    await lifecycle_action(state, lifecycle.resume, cid)
    assert (await run_tick(app, state, smtp)).spent == 2
    assert sorted(sent_to(smtp)) == sorted(emails)
    assert (await campaign_row(state, T, cid)).status == "sent"


async def test_dispatch_lock_busy_skips(built):
    app, state = built
    await started(state, 2, at=NINE)
    smtp = FakeTransport()

    async with dispatch_lock(state.session_factory, holder="someone-else"):
        summary = await run_tick(app, state, smtp, lock_wait_s=0.2)

    assert (summary.stopped, summary.spent) == ("busy", 0)
    assert smtp.sent == [] and await attempts(state) == []


async def test_no_work_opens_no_transport(built):
    app, state = built
    smtp = FakeTransport()

    summary = await run_tick(app, state, smtp)

    assert summary.stopped == "idle"
    assert smtp.opened == 0


async def test_freeze_then_send_in_one_tick(tmp_path):
    app, state, _ = await world(tmp_path, daily_limit=1, per_minute_limit=100)
    try:
        cid, _ = await due(state, 2)
        smtp = FakeTransport()

        summary = await run_tick(app, state, smtp)

        assert (summary.started, summary.spent) == (1, 1)
        assert (await campaign_row(state, T, cid)).status == "sending"
        assert len(smtp.sent) == 1
    finally:
        await state.engine.dispose()
