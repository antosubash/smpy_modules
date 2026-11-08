"""Delivering one recipient (Task 6): the re-check before sending, and every
way the reservation can lose (amendments A3, A4) without sending anything."""

from __future__ import annotations

import pytest
from sm_newsletter.campaigns import lifecycle
from sm_newsletter.core.errors import DispatchBusy
from sm_newsletter.core.suppression import suppress
from sm_newsletter.sending import deliver as delivering
from sm_newsletter.sending.classify import Verdict
from sm_newsletter.sending.deliver import Step
from sm_records.contracts.newsletter import unsubscribe
from sm_records.core.settings import RecordsSettings

from tests.support.campaign_world import (
    campaign_row,
    seed_campaign,
    seed_render,
    seed_sends,
    send_rows,
    set_columns,
)
from tests.support.deliver_world import (
    FENCED_OUT,
    LOST_LEASE,
    attempts,
    counters,
    deliver,
    in_other_session,
    one_row,
    sending_campaign,
    set_send_status,
)
from tests.support.dispatch_world import lifecycle_action
from tests.support.fake_transport import FakeTransport
from tests.support.freeze_world import world
from tests.support.sending import NOW, T

SKIP = Step(False, Verdict("skip", False))


async def _nothing_happened(state, cid, smtp, status="queued") -> None:
    assert smtp.sent == []
    assert await attempts(state) == []
    assert (await one_row(state, cid)).status == status


def _after_eligibility(monkeypatch, work) -> None:
    """Run ``await work()`` right after the subscriber read, before the claim."""
    real = delivering.subscribers_by_uuid

    async def wrapped(session, **kw):
        hits = await real(session, **kw)
        await work()
        return hits

    monkeypatch.setattr(delivering, "subscribers_by_uuid", wrapped)


async def test_unsubscribed_since_freeze_is_skipped(state):
    cid, _ = await sending_campaign(state)
    row = await one_row(state, cid)

    async def leave(db) -> None:
        assert await unsubscribe(
            db,
            tenant_id=T,
            type_key="news",
            uuid=row.record_uuid,
            unless_confirmed_after=None,
            settings=RecordsSettings(),
        )

    await in_other_session(state, leave)
    smtp = FakeTransport()

    assert await deliver(state, cid, smtp) == SKIP
    await _nothing_happened(state, cid, smtp, status="skipped_unsubscribed")


@pytest.mark.parametrize("change", ["missing", "trashed", "pending"])
async def test_ineligible_subscriber_is_skipped(state, monkeypatch, change):
    cid, _ = await sending_campaign(state)
    real = delivering.subscribers_by_uuid

    async def changed(session, **kw):
        hits = await real(session, **kw)
        if change == "missing":
            return {}
        update = {"trashed": True} if change == "trashed" else {"status": "pending"}
        return {uuid: hit.model_copy(update=update) for uuid, hit in hits.items()}

    monkeypatch.setattr(delivering, "subscribers_by_uuid", changed)
    smtp = FakeTransport()

    assert await deliver(state, cid, smtp) == SKIP
    await _nothing_happened(state, cid, smtp, status="skipped_unsubscribed")


async def test_suppressed_since_freeze_is_skipped(state):
    cid, (email,) = await sending_campaign(state)

    async def complain(db) -> None:
        await suppress(db, tenant_id=T, email=email, reason="complaint", source="admin")

    await in_other_session(state, complain)
    smtp = FakeTransport()

    assert await deliver(state, cid, smtp) == SKIP
    await _nothing_happened(state, cid, smtp, status="suppressed")
    assert (await counters(state, cid))["suppressed_count"] == 1


@pytest.mark.parametrize("status", ["paused", "cancelled"])
async def test_campaign_not_sending_sends_nothing(state, status):
    cid, _ = await sending_campaign(state)
    await set_columns(state, T, cid, status=status)
    smtp = FakeTransport()

    assert await deliver(state, cid, smtp) is None
    await _nothing_happened(state, cid, smtp)


async def test_lost_lease_sends_nothing(state):
    cid, _ = await sending_campaign(state)
    smtp = FakeTransport()

    with pytest.raises(DispatchBusy):
        await deliver(state, cid, smtp, lock=LOST_LEASE)
    await _nothing_happened(state, cid, smtp)
    assert (await one_row(state, cid)).lease_until is None


async def test_fence_failure_rolls_back_the_reservation(state):
    cid, _ = await sending_campaign(state)
    smtp = FakeTransport()

    with pytest.raises(DispatchBusy):
        await deliver(state, cid, smtp, lock=FENCED_OUT)
    await _nothing_happened(state, cid, smtp)
    assert (await one_row(state, cid)).lease_until is None


async def test_pause_before_claim_sends_nothing(state, monkeypatch):
    cid, _ = await sending_campaign(state)
    _after_eligibility(monkeypatch, lambda: lifecycle_action(state, lifecycle.pause, cid))
    smtp = FakeTransport()

    assert await deliver(state, cid, smtp) is None
    await _nothing_happened(state, cid, smtp)
    assert (await campaign_row(state, T, cid)).status == "paused"


async def test_cancel_before_claim_sends_nothing(state, monkeypatch):
    cid, _ = await sending_campaign(state)
    _after_eligibility(monkeypatch, lambda: lifecycle_action(state, lifecycle.cancel, cid))
    smtp = FakeTransport()

    assert await deliver(state, cid, smtp) is None
    await _nothing_happened(state, cid, smtp, status="cancelled")


async def test_claim_requires_queued_row(state, monkeypatch):
    cid, _ = await sending_campaign(state)
    row = await one_row(state, cid)
    _after_eligibility(monkeypatch, lambda: set_send_status(state, row.id, "sending"))
    smtp = FakeTransport()

    assert await deliver(state, cid, smtp) is None
    await _nothing_happened(state, cid, smtp, status="sending")


@pytest.mark.unbound_tenant
async def test_tenant_pinned(tmp_path):
    _, state, _ = await world(tmp_path)
    try:
        cid = await seed_campaign(state, "b", status="sending", started_at=NOW)
        await seed_render(state, "b", cid)
        await seed_sends(state, "b", cid, ["queued"])
        smtp = FakeTransport()

        assert await deliver(state, cid, smtp, tenant="a") is None

        assert smtp.sent == []
        assert [row.status for row in await send_rows(state, "b", cid)] == ["queued"]
        assert await attempts(state, "a") == [] and await attempts(state, "b") == []
    finally:
        await state.engine.dispose()


async def test_skip_never_overwrites_a_row_that_moved(state, monkeypatch):
    """The skip ``UPDATE`` is conditional on ``queued``."""
    cid, _ = await sending_campaign(state)
    row = await one_row(state, cid)

    async def gone(session, **kw):
        await set_send_status(state, row.id, "cancelled")
        return {}

    monkeypatch.setattr(delivering, "subscribers_by_uuid", gone)

    assert await deliver(state, cid, FakeTransport()) == SKIP
    assert (await one_row(state, cid)).status == "cancelled"
