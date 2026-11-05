"""The freeze fence (amendments A1, A2): one owner per campaign and generation,
re-checked inside every page's transaction."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns import lifecycle
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.sending import freeze as freezing

from tests.support.campaign_world import campaign_row, send_rows, set_columns
from tests.support.freeze_world import (
    Pause,
    due_campaign,
    emails,
    gate_page,
    run_freeze,
    schedule,
    statuses,
    subscribers,
    unschedule,
    world,
)
from tests.support.records_seed import seed_list, seed_subscriber
from tests.support.sending import NOW, T


@pytest.fixture
async def built(tmp_path):
    app, state, draft = await world(tmp_path)
    yield app, state, draft
    await state.engine.dispose()


async def test_cancel_during_freeze_leaves_no_queued_rows(built, monkeypatch):
    _, state, _ = built
    monkeypatch.setattr(freezing, "PAGE", 2)
    await subscribers(state, 4)
    cid = await due_campaign(state)

    async def cancel() -> None:
        async with state.session_factory() as db:
            await lifecycle.cancel(db, tenant_id=T, campaign_id=cid, roles=[], now=NOW)
            await finalize_session(db)

    gate_page(monkeypatch, 2, cancel)
    assert await run_freeze(state, cid) == freezing.FreezeResult(False, 0, 0)

    assert (await campaign_row(state, T, cid)).status == "cancelled"
    assert await statuses(state, cid) == {"cancelled": 2}


@pytest.mark.unbound_tenant
async def test_interrupted_freeze_then_unschedule_reschedule_uses_new_list(built, monkeypatch):
    app, state, _ = built
    monkeypatch.setattr(freezing, "PAGE", 2)
    await seed_list(state, T, "other")
    await subscribers(state, 3)
    others = await subscribers(state, 2, key="other", prefix="o")
    cid = await due_campaign(state)

    async def crash() -> None:
        raise RuntimeError("worker killed")

    gate_page(monkeypatch, 2, crash)
    with pytest.raises(RuntimeError, match="worker killed"):
        await run_freeze(state, cid)
    old_gen = (await campaign_row(state, T, cid)).freeze_gen
    assert len(await send_rows(state, T, cid)) == 2

    await unschedule(state, cid)
    await set_columns(state, T, cid, list_type_key="other")
    await schedule(app, state, cid)
    assert await freezing.start_due(state.session_factory, now=NOW) == 1

    campaign = await campaign_row(state, T, cid)
    assert (campaign.status, campaign.recipient_count) == ("sending", 2)
    assert campaign.freeze_gen > old_gen
    assert await emails(state, cid) == sorted(others)
    assert {row.freeze_gen for row in await send_rows(state, T, cid)} == {campaign.freeze_gen}


async def test_stale_freezer_after_reschedule_writes_nothing(built, monkeypatch):
    """The reschedule moves the campaign to another list, so a page the stale
    freezer wrote from the old one would show."""
    app, state, _ = built
    monkeypatch.setattr(freezing, "PAGE", 2)
    await seed_list(state, T, "other")
    await subscribers(state, 4)
    others = await subscribers(state, 3, key="other", prefix="o")
    cid = await due_campaign(state)
    pause = Pause()
    gate_page(monkeypatch, 2, pause)

    stale = asyncio.create_task(run_freeze(state, cid))
    await pause.reached.wait()
    await unschedule(state, cid)
    await set_columns(state, T, cid, list_type_key="other")
    await schedule(app, state, cid)
    fresh = await run_freeze(state, cid)
    pause.go.set()

    assert fresh == freezing.FreezeResult(True, 3, 0)
    assert await stale == freezing.FreezeResult(False, 0, 0)
    campaign = await campaign_row(state, T, cid)
    assert (campaign.status, campaign.recipient_count, campaign.suppressed_count) == (
        "sending",
        3,
        0,
    )
    rows = await send_rows(state, T, cid)
    assert sorted(row.email for row in rows) == sorted(others)
    assert {row.freeze_gen for row in rows} == {campaign.freeze_gen}


async def test_overlapping_freezes_one_owner(built, monkeypatch):
    _, state, _ = built
    await subscribers(state, 2)
    cid = await due_campaign(state)
    pause = Pause()
    gate_page(monkeypatch, 1, pause)

    async def second() -> freezing.FreezeResult:
        await pause.reached.wait()
        result = await run_freeze(state, cid)
        await seed_subscriber(state, T, "late@example.org", "confirmed")
        pause.go.set()
        return result

    first, other = await asyncio.gather(run_freeze(state, cid), second())

    assert first == freezing.FreezeResult(True, 3, 0)
    assert other == freezing.FreezeResult(False, 0, 0)
    campaign = await campaign_row(state, T, cid)
    assert campaign.recipient_count == len(await send_rows(state, T, cid)) == 3


async def test_live_claim_is_not_taken_and_claiming_keeps_the_revision(built):
    _, state, _ = built
    cid = await due_campaign(state)
    before = await campaign_row(state, T, cid)
    async with state.session_factory() as db:
        claim = await freezing.claim_freeze(db, tenant_id=T, campaign_id=cid, now=NOW)
        await finalize_session(db)
    assert claim is not None and claim.owner.startswith("freeze:")
    assert claim.gen == before.freeze_gen
    held = await campaign_row(state, T, cid)
    assert (held.freeze_owner, held.freeze_until) == (claim.owner, NOW + freezing.FREEZE_LEASE)
    assert held.revision == before.revision

    assert await run_freeze(state, cid) == freezing.FreezeResult(False, 0, 0)
    assert (await campaign_row(state, T, cid)).freeze_owner == claim.owner


async def test_expired_freeze_lease_is_taken_over(built):
    _, state, _ = built
    await subscribers(state, 1)
    cid = await due_campaign(state)
    gen = (await campaign_row(state, T, cid)).freeze_gen
    old = freezing.FreezeClaim(owner="freeze:old", gen=gen)
    await set_columns(
        state, T, cid, freeze_owner=old.owner, freeze_until=NOW - timedelta(seconds=1)
    )

    assert await run_freeze(state, cid) == freezing.FreezeResult(True, 1, 0)

    with tenant_scope(T):
        async with state.session_factory() as db:
            held = await freezing.hold_freeze(db, old, tenant_id=T, campaign_id=cid, now=NOW)
            await finalize_session(db)
    assert held is False
    assert (await campaign_row(state, T, cid)).status == "sending"
