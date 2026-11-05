"""Pause, resume and cancel (ruling S14), the tenant pin and the paused reason."""

from __future__ import annotations

import asyncio

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns import lifecycle
from sm_newsletter.core.constants import CAMPAIGN_STATUSES
from sm_newsletter.core.errors import InvalidTransition, NewsletterError, NotFound
from sm_newsletter.core.tenancy import tenant_scope

from tests.support.campaign_world import campaign_row, seed_campaign, seed_sends, send_rows
from tests.support.records_seed import seed_list
from tests.support.sending import NOW, T, make_app

ACTIONS = {"pause": lifecycle.pause, "resume": lifecycle.resume, "cancel": lifecycle.cancel}
# (action, from) -> to; every other pair is 409 ``invalid_transition``.
ALLOWED = {
    ("pause", "sending"): "paused",
    ("resume", "paused"): "sending",
    ("cancel", "scheduled"): "cancelled",
    ("cancel", "sending"): "cancelled",
    ("cancel", "paused"): "cancelled",
}


async def _act(state, action, cid, *, tenant=T, roles=()):
    async with state.session_factory() as db:
        campaign = await ACTIONS[action](
            db, tenant_id=tenant, campaign_id=cid, roles=list(roles), now=NOW
        )
        await finalize_session(db)
        return campaign


@pytest.mark.parametrize("status", CAMPAIGN_STATUSES)
@pytest.mark.parametrize("action", list(ACTIONS))
async def test_action_matrix(built, action, status):
    _, state, _ = built
    cid = await seed_campaign(state, T, status=status, started_at=NOW)
    before = await campaign_row(state, T, cid)
    target = ALLOWED.get((action, status))
    if target is None:
        with pytest.raises(InvalidTransition) as err:
            await _act(state, action, cid)
        assert (err.value.status, err.value.code) == (409, "invalid_transition")
        after = await campaign_row(state, T, cid)
        assert (after.status, after.revision) == (status, before.revision)
        return
    campaign = await _act(state, action, cid)
    assert (campaign.status, campaign.revision) == (target, before.revision + 1)
    if action == "pause":
        assert lifecycle.split_paused(campaign.paused_reason) == ("manual", None)
    if action == "resume":
        assert campaign.paused_reason is None
    if action == "cancel":
        assert campaign.finished_at == NOW


async def test_resume_before_freeze_goes_back_to_scheduled(built):
    _, state, _ = built
    cid = await seed_campaign(state, T, status="paused", started_at=None)
    async with state.session_factory() as db:
        ok = await lifecycle.transition(
            db,
            tenant_id=T,
            campaign_id=cid,
            from_statuses=("paused",),
            values={"paused_reason": lifecycle.paused_reason("list_unavailable")},
        )
        assert ok
        await finalize_session(db)
    campaign = await _act(state, "resume", cid)
    assert (campaign.status, campaign.scheduled_at, campaign.paused_reason) == (
        "scheduled",
        NOW,
        None,
    )
    assert campaign.started_at is None


async def test_cancel_from_scheduled_bumps_freeze_gen(built):
    _, state, _ = built
    scheduled = await seed_campaign(state, T, status="scheduled", scheduled_at=NOW)
    sending = await seed_campaign(state, T, status="sending", started_at=NOW)
    assert (await _act(state, "cancel", scheduled, tenant=T)).freeze_gen == 1
    assert (await _act(state, "cancel", sending, tenant=T)).freeze_gen == 0


async def test_cancel_marks_only_queued_rows(built):
    _, state, _ = built
    cid = await seed_campaign(state, T, status="sending", started_at=NOW)
    other = await seed_campaign(state, T, status="sending", started_at=NOW)
    await seed_sends(state, T, cid, ["queued", "sending", "sent"])
    await seed_sends(state, T, other, ["queued"])
    await _act(state, "cancel", cid)
    assert [r.status for r in await send_rows(state, T, cid)] == ["cancelled", "sending", "sent"]
    assert [r.status for r in await send_rows(state, T, other)] == ["queued"]


async def test_two_concurrent_cancels_one_wins(tmp_path):
    _, state, _ = await make_app(file=tmp_path / "race.db")
    try:
        cid = await seed_campaign(state, T, status="sending", started_at=NOW)
        await seed_sends(state, T, cid, ["queued", "queued"])

        async def attempt() -> str:
            try:
                await _act(state, "cancel", cid)
            except NewsletterError as exc:
                return f"{exc.status} {exc.code}"
            return "won"

        outcomes = await asyncio.gather(attempt(), attempt())
        assert sorted(outcomes) == ["409 invalid_transition", "won"]
        campaign = await campaign_row(state, T, cid)
        assert (campaign.status, campaign.revision) == ("cancelled", 2)
        assert [r.status for r in await send_rows(state, T, cid)] == ["cancelled", "cancelled"]
    finally:
        await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_transition_pins_the_tenant():
    """Tenant B's campaign id used under tenant A: 404, and B is unchanged."""
    with tenant_scope(T):
        _, state, _ = await make_app()
    try:
        await seed_list(state, "b")
        theirs = await seed_campaign(state, "b", status="sending", started_at=NOW)
        await seed_sends(state, "b", theirs, ["queued"])
        with tenant_scope(T):
            for action in ACTIONS:
                with pytest.raises(NotFound):
                    await _act(state, action, theirs, tenant=T)
            async with state.session_factory() as db:
                changed = await lifecycle.transition(
                    db,
                    tenant_id=T,
                    campaign_id=theirs,
                    from_statuses=("sending",),
                    values={"status": "paused"},
                )
                assert changed is False
                await finalize_session(db)
        campaign = await campaign_row(state, "b", theirs)
        assert (campaign.status, campaign.revision) == ("sending", 1)
        assert [r.status for r in await send_rows(state, "b", theirs)] == ["queued"]
    finally:
        await state.engine.dispose()


def test_paused_reason_round_trip():
    reason = lifecycle.paused_reason("smtp_rejected", "554 5.4.5 x")
    assert reason == "smtp_rejected|554 5.4.5 x"
    assert lifecycle.split_paused(reason) == ("smtp_rejected", "554 5.4.5 x")
    assert lifecycle.split_paused(lifecycle.paused_reason("manual")) == ("manual", None)
    assert lifecycle.split_paused(None) == (None, None)
    long = lifecycle.paused_reason("smtp_rejected", "x" * 2000)
    assert len(long) == 1000 and long.startswith("smtp_rejected|x")
    with pytest.raises(ValueError):
        lifecycle.paused_reason("bogus", "x")
