"""Freeze (ruling S18): a due campaign's audience becomes send rows, and
``start_due`` walks every tenant's due campaigns."""

from __future__ import annotations

from datetime import timedelta

import pytest
from simple_module_db import finalize_session
from simple_module_db.listeners import TenantIsolationError
from sm_newsletter.campaigns import lifecycle
from sm_newsletter.core.constants import MAX_EMAIL_LEN
from sm_newsletter.core.suppression import suppress
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.sending import freeze as freezing

from tests.support.campaign_world import campaign_row, seed_campaign, send_rows, set_columns
from tests.support.freeze_world import (
    due_campaign,
    emails,
    run_freeze,
    start_due,
    statuses,
    subscribers,
    world,
)
from tests.support.records_seed import seed_list, seed_subscriber, set_list_kind
from tests.support.sending import NOW, T


@pytest.fixture
async def built(tmp_path):
    app, state, draft = await world(tmp_path)
    yield app, state, draft
    await state.engine.dispose()


async def test_freeze_queues_confirmed_only(built):
    _, state, _ = built
    await seed_subscriber(state, T, "ada@example.org", "confirmed")
    await seed_subscriber(state, T, "pending@example.org", "pending")
    await seed_subscriber(state, T, "gone@example.org", "unsubscribed")
    cid = await due_campaign(state)

    result = await run_freeze(state, cid)

    assert result == freezing.FreezeResult(started=True, queued=1, suppressed=0)
    (row,) = await send_rows(state, T, cid)
    assert (row.email, row.status, row.tenant_id) == ("ada@example.org", "queued", T)
    campaign = await campaign_row(state, T, cid)
    assert (campaign.status, campaign.started_at, campaign.recipient_count) == ("sending", NOW, 1)
    assert (campaign.freeze_owner, campaign.freeze_until) == (None, None)
    assert row.freeze_gen == campaign.freeze_gen


async def test_freeze_copies_first_name(built, monkeypatch):
    _, state, _ = built
    await seed_subscriber(state, T, "ada@example.org", "confirmed")
    real = freezing.iter_subscribers

    async def named(session, **kw):
        hits, nxt = await real(session, **kw)
        return [hit.model_copy(update={"first_name": "Ada"}) for hit in hits], nxt

    monkeypatch.setattr(freezing, "iter_subscribers", named)
    cid = await due_campaign(state)
    await run_freeze(state, cid)
    assert [row.first_name for row in await send_rows(state, T, cid)] == ["Ada"]


async def test_freeze_clips_a_long_first_name_and_skips_a_too_long_email(built, monkeypatch):
    """Records caps neither, but the send columns do: Postgres would refuse the
    page (``StringDataRightTruncation``) and wedge the freeze forever."""
    _, state, _ = built
    ada = await seed_subscriber(state, T, "ada@example.org", "confirmed")
    await seed_subscriber(state, T, "long@example.org", "confirmed")
    real = freezing.iter_subscribers
    too_long = "x" * MAX_EMAIL_LEN + "@example.org"

    async def odd(session, **kw):
        hits, nxt = await real(session, **kw)
        return [
            hit.model_copy(update={"first_name": "A" * 300})
            if hit.uuid == ada
            else hit.model_copy(update={"email": too_long})
            for hit in hits
        ], nxt

    monkeypatch.setattr(freezing, "iter_subscribers", odd)
    cid = await due_campaign(state)

    assert await run_freeze(state, cid) == freezing.FreezeResult(True, 1, 0)
    (row,) = await send_rows(state, T, cid)
    assert (row.email, row.first_name) == ("ada@example.org", "A" * 200)
    assert (await campaign_row(state, T, cid)).status == "sending"


async def test_freeze_marks_suppressed_rows(built):
    _, state, _ = built
    await subscribers(state, 3)
    async with state.session_factory() as db:
        await suppress(db, tenant_id=T, email="S1@example.org", reason="hard_bounce", source="send")
        await finalize_session(db)
    cid = await due_campaign(state)

    assert await run_freeze(state, cid) == freezing.FreezeResult(True, 2, 1)
    assert {row.email: row.status for row in await send_rows(state, T, cid)}["s1@example.org"] == (
        "suppressed"
    )
    campaign = await campaign_row(state, T, cid)
    assert (campaign.recipient_count, campaign.suppressed_count) == (2, 1)


async def test_freeze_is_idempotent(built):
    _, state, _ = built
    await subscribers(state, 3)
    cid = await due_campaign(state)
    await run_freeze(state, cid)
    await set_columns(state, T, cid, status="scheduled")

    assert await run_freeze(state, cid) == freezing.FreezeResult(True, 3, 0)
    assert len(await send_rows(state, T, cid)) == 3
    assert (await campaign_row(state, T, cid)).recipient_count == 3


async def test_freeze_pages(built, monkeypatch):
    _, state, _ = built
    monkeypatch.setattr(freezing, "PAGE", 2)
    expected = await subscribers(state, 5)
    cid = await due_campaign(state)
    assert (await run_freeze(state, cid)).queued == 5
    assert await emails(state, cid) == sorted(expected)


async def test_freeze_skips_a_campaign_without_render(built, caplog):
    _, state, _ = built
    cid = await seed_campaign(state, T, status="scheduled", scheduled_at=NOW)
    assert not (await run_freeze(state, cid)).started
    assert (await campaign_row(state, T, cid)).status == "scheduled"
    assert any(r.levelname == "ERROR" for r in caplog.records)


async def test_freeze_list_gone_pauses(built):
    _, state, _ = built
    await subscribers(state, 1)
    cid = await due_campaign(state)
    before = await campaign_row(state, T, cid)
    await set_list_kind(state, T, "news", "form")

    assert not (await run_freeze(state, cid)).started

    campaign = await campaign_row(state, T, cid)
    assert campaign.status == "paused"
    assert campaign.paused_reason.startswith("list_unavailable|")
    assert campaign.started_at is None
    assert (campaign.freeze_owner, campaign.freeze_until) == (None, None)
    assert (campaign.revision, campaign.freeze_gen) == (before.revision + 1, before.freeze_gen)
    assert await send_rows(state, T, cid) == []


@pytest.mark.unbound_tenant
async def test_list_restored_then_resumed_freezes_at_once(built):
    _, state, _ = built
    await subscribers(state, 2)
    cid = await due_campaign(state)
    await set_list_kind(state, T, "news", "form")
    await run_freeze(state, cid)
    await set_list_kind(state, T, "news", "subscription")
    with tenant_scope(T):
        async with state.session_factory() as db:
            resumed = await lifecycle.resume(db, tenant_id=T, campaign_id=cid, roles=[], now=NOW)
            await finalize_session(db)
    assert resumed.status == "scheduled"

    assert await start_due(state) == 1
    assert (await campaign_row(state, T, cid)).status == "sending"
    assert await statuses(state, cid) == {"queued": 2}


@pytest.mark.unbound_tenant
async def test_start_due_only_due_and_scheduled(built):
    _, state, draft = built
    await subscribers(state, 1)
    due = await due_campaign(state)
    later = await seed_campaign(
        state, T, status="scheduled", scheduled_at=NOW + timedelta(minutes=5)
    )

    assert await start_due(state) == 1

    assert (await campaign_row(state, T, due)).status == "sending"
    for cid, status in ((later, "scheduled"), (draft, "draft")):
        assert (await campaign_row(state, T, cid)).status == status
        assert await send_rows(state, T, cid) == []


@pytest.mark.unbound_tenant
async def test_start_due_per_tenant(built):
    _, state, _ = built
    cids = {}
    for tenant in ("a", "b"):
        await seed_list(state, tenant)
        await subscribers(state, 1, tenant=tenant, prefix=tenant)
        cids[tenant] = await due_campaign(state, tenant)

    assert await start_due(state) == 2

    for tenant, cid in cids.items():
        rows = await send_rows(state, tenant, cid)
        assert [(r.email, r.tenant_id) for r in rows] == [(f"{tenant}0@example.org", tenant)]


@pytest.mark.unbound_tenant
async def test_start_due_goes_on_after_a_failure(built, monkeypatch, caplog):
    _, state, _ = built
    first, second = await due_campaign(state), await due_campaign(state)
    real = freezing.freeze

    async def flaky(factory, *, campaign_id, **kw):
        if campaign_id == first:
            raise RuntimeError("boom ada@example.org")
        return await real(factory, campaign_id=campaign_id, **kw)

    monkeypatch.setattr(freezing, "freeze", flaky)
    assert await start_due(state) == 1
    assert (await campaign_row(state, T, second)).status == "sending"
    # The class only: a database error's text carries the page's SQL parameters
    # (addresses and names), so neither the message nor a traceback is logged.
    [failure] = [r for r in caplog.records if "could not freeze" in r.getMessage()]
    assert "RuntimeError" in failure.getMessage()
    assert "ada@example.org" not in failure.getMessage()
    assert failure.exc_info is None


@pytest.mark.unbound_tenant
async def test_start_due_refuses_a_bound_tenant(built):
    """Seeded unbound (``other`` cannot be bound inside ``default``), then run
    under ``default`` as the autouse fixture binds it."""
    _, state, _ = built
    await seed_list(state, "other")
    cid = await due_campaign(state, "other")
    with tenant_scope(T), pytest.raises(TenantIsolationError):
        await start_due(state)
    assert (await campaign_row(state, "other", cid)).status == "scheduled"
