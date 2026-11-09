"""Delivering one recipient (Task 6): the reservation before SMTP, and what
each verdict does to the row and the campaign (rulings S4, S7, S17)."""

from __future__ import annotations

from datetime import timedelta

from sm_newsletter.campaigns.lifecycle import split_paused
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import CampaignRender, Send, SendAttempt
from sm_newsletter.sending import rows
from sm_newsletter.sending.classify import Verdict
from sm_newsletter.sending.deliver import Step
from sm_newsletter.sending.transport import DeliveryResult
from sm_newsletter.tracking.rewrite import Tracking
from sqlalchemy import select, update

from tests.support.campaign_world import campaign_row
from tests.support.deliver_world import (
    attempts,
    counters,
    deliver,
    in_other_session,
    is_suppressed,
    one_row,
    sending_campaign,
)
from tests.support.fake_transport import FakeTransport
from tests.support.sending import NOW, T
from tests.support.tracking_world import track_render


async def test_accepted_marks_sent_and_counts(state):
    cid, (email,) = await sending_campaign(state)
    smtp = FakeTransport()

    assert await deliver(state, cid, smtp) == Step(True, Verdict("sent", False))

    row = await one_row(state, cid)
    assert (row.status, row.sent_at, row.attempts) == ("sent", NOW, 1)
    assert (row.lease_until, row.last_error, row.error_kind) == (None, None, None)
    assert (await counters(state, cid))["sent_count"] == 1
    (attempt,) = await attempts(state)
    assert (attempt.send_id, attempt.campaign_id, attempt.kind) == (row.id, cid, "campaign")
    assert (attempt.outcome, attempt.recipient) == ("accepted", email)
    assert [m.to for m in smtp.sent] == [email]
    assert smtp.sent[0].ref == f"campaign={cid} send={row.id}"
    assert await deliver(state, cid, smtp) is None  # nothing left


async def test_attempt_and_claim_committed_before_smtp(state):
    cid, _ = await sending_campaign(state)
    seen: list[tuple] = []

    async def probe(_msg) -> None:
        with tenant_scope(T):
            async with state.session_factory() as db:
                send = (await db.execute(select(Send).where(Send.tenant_id == T))).scalar_one()
                stmt = select(SendAttempt).where(SendAttempt.send_id == send.id)
                attempt = (await db.execute(stmt)).scalar_one()
                seen.append((send.status, send.lease_until, attempt.outcome))

    await deliver(state, cid, FakeTransport(on_send=probe))

    assert seen == [("sending", NOW + rows.LEASE, "pending")]


async def test_retry_backoff_then_exhausted(state):
    cid, (email,) = await sending_campaign(state)
    soft = DeliveryResult("rejected", 451, "4.3.0 Try again later", "data")
    smtp = FakeTransport({email: soft})

    step = await deliver(state, cid, smtp)
    assert step == Step(True, Verdict("retry", False))
    row = await one_row(state, cid)
    first_retry = NOW + timedelta(minutes=5)
    assert (row.status, row.attempts, row.retry_at) == ("queued", 1, first_retry)
    assert (row.lease_until, row.last_error) == (None, "4.3.0 Try again later")

    early = first_retry - timedelta(seconds=1)
    assert await deliver(state, cid, smtp, now=early) is None
    with tenant_scope(T):
        async with state.session_factory() as db:
            assert await rows.next_row(db, tenant_id=T, campaign_id=cid, now=early) is None

    await deliver(state, cid, smtp, now=first_retry)
    row = await one_row(state, cid)
    second_retry = first_retry + timedelta(minutes=30)
    assert (row.status, row.attempts, row.retry_at) == ("queued", 2, second_retry)
    assert (await counters(state, cid))["failed_count"] == 0

    await deliver(state, cid, smtp, now=second_retry)
    row = await one_row(state, cid)
    assert (row.status, row.error_kind, row.attempts) == ("failed", "retries_exhausted", 3)
    assert row.retry_at is None  # terminal: no stale schedule
    assert (await counters(state, cid))["failed_count"] == 1
    assert len(smtp.sent) == 3
    assert await deliver(state, cid, smtp, now=second_retry + timedelta(days=1)) is None


async def test_unknown_is_failed_never_retried(state):
    cid, (email,) = await sending_campaign(state)
    dropped = DeliveryResult("unknown", None, "connection lost after the body", "data")
    smtp = FakeTransport({email: dropped})

    assert (await deliver(state, cid, smtp)).verdict.action == "unknown"

    row = await one_row(state, cid)
    assert (row.status, row.error_kind, row.attempts) == ("failed", "outcome_unknown", 1)
    assert (await counters(state, cid))["failed_count"] == 1
    assert [a.outcome for a in await attempts(state)] == ["unknown"]
    assert await deliver(state, cid, smtp, now=NOW + timedelta(days=1)) is None
    assert len(smtp.sent) == 1


async def test_bounce_suppresses_tenant_wide(state):
    cid, (email,) = await sending_campaign(state)
    smtp = FakeTransport({email: DeliveryResult("rejected", 550, "5.1.1 No such user", "rcpt")})

    assert (await deliver(state, cid, smtp)).verdict.action == "bounce"

    row = await one_row(state, cid)
    assert (row.status, row.last_error) == ("bounced", "5.1.1 No such user")
    assert (await counters(state, cid))["bounced_count"] == 1
    assert await is_suppressed(state, email.upper())


async def test_pause_reply_leaves_row_queued_and_pauses(state):
    cid, (email,) = await sending_campaign(state)
    quota = DeliveryResult("rejected", 554, "5.4.5 Daily sending quota exceeded", "data")
    smtp = FakeTransport({email: quota})

    step = await deliver(state, cid, smtp)

    assert step is not None and step.spent and step.verdict.stop_tick
    row = await one_row(state, cid)
    assert (row.status, row.attempts, row.lease_until) == ("queued", 0, None)
    campaign = await campaign_row(state, T, cid)
    assert campaign.status == "paused"
    assert split_paused(campaign.paused_reason) == (
        "smtp_rejected",
        "554 5.4.5 Daily sending quota exceeded",
    )
    assert not await is_suppressed(state, email)
    assert await deliver(state, cid, smtp) is None  # paused: nothing more


async def test_rejected_without_code_fails_invalid(state):
    cid, (email,) = await sending_campaign(state)
    refused = DeliveryResult("rejected", None, "to must not contain line breaks")
    smtp = FakeTransport({email: refused})

    assert (await deliver(state, cid, smtp)).verdict.action == "fail"

    row = await one_row(state, cid)
    assert (row.status, row.error_kind) == ("failed", "invalid_message")
    assert (await counters(state, cid))["failed_count"] == 1


async def test_invalid_message_fails_before_any_attempt(state):
    cid, _ = await sending_campaign(state)

    async def break_subject(db) -> None:
        await db.execute(
            update(CampaignRender)
            .where(CampaignRender.tenant_id == T, CampaignRender.campaign_id == cid)
            .values(subject="Hi\r\nBcc: x@evil.test")
        )

    await in_other_session(state, break_subject)
    smtp = FakeTransport()

    step = await deliver(state, cid, smtp)

    assert step == Step(False, Verdict("fail", False, error_kind="invalid_message"))
    row = await one_row(state, cid)
    assert (row.status, row.error_kind) == ("failed", "invalid_message")
    assert (await counters(state, cid))["failed_count"] == 1
    assert (smtp.sent, await attempts(state)) == ([], [])


async def test_deliver_passes_tracking_and_links(state):
    cid, _ = await sending_campaign(state)
    await track_render(state, cid)
    smtp = FakeTransport()

    await deliver(state, cid, smtp, tracking=Tracking(True, True))

    (message,) = smtp.sent
    assert "/newsletter/c/" in message.html and "/newsletter/o/" in message.html
