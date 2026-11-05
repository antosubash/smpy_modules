"""Freeze reads the audience snapshotted at scheduling, under its claim, and
pauses (or waits) when records refuses the stored terms."""

from __future__ import annotations

import logging

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns import drafts
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import CampaignRender, Segment
from sm_newsletter.segments import store
from sm_newsletter.segments.rules import Rule
from sm_newsletter.sending import freeze as freezing
from sm_newsletter.web.schemas.campaigns import CampaignPatch
from sm_records.contracts.newsletter import SubscriberFilterError
from sqlalchemy import delete, update

from tests.support.campaign_world import campaign_row, send_rows, set_columns
from tests.support.freeze_world import (
    emails,
    run_freeze,
    schedule,
    start_due,
    unschedule,
    world,
)
from tests.support.records_seed import TAGS, seed_list, seed_subscriber
from tests.support.sending import T

LIST = "tagged"
ADA, BOB, CY = "ada@example.org", "bob@example.org", "cy@example.org"


@pytest.fixture
async def built(tmp_path):
    """The app, its state and a draft on ``tagged``: ada ``vip``, bob
    ``events``, cy untagged."""
    app, state, cid = await world(tmp_path)
    await seed_list(state, T, LIST, fields=[TAGS])
    for email, tags in ((ADA, ["vip"]), (BOB, ["events"]), (CY, [])):
        await seed_subscriber(state, T, email, "confirmed", LIST, data={"tags": tags})
    await set_columns(state, T, cid, list_type_key=LIST)
    yield app, state, cid
    await state.engine.dispose()


async def _segment(state, tag: str) -> int:
    with tenant_scope(T):
        async with state.session_factory() as db:
            seg = await store.create_segment(
                db,
                tenant_id=T,
                roles=[],
                name="Seg",
                list_type_key=LIST,
                rules=[Rule(field="tags", op="any", value=[tag])],
            )
            await finalize_session(db)
            return seg.id


async def _edit_segment(state, segment_id: int, tag: str) -> None:
    with tenant_scope(T):
        async with state.session_factory() as db:
            await store.update_segment(
                db,
                tenant_id=T,
                segment_id=segment_id,
                roles=[],
                name=None,
                rules=[Rule(field="tags", op="any", value=[tag])],
            )
            await finalize_session(db)


async def _segment_campaign(app, state, cid, tag: str = "vip") -> int:
    seg = await _segment(state, tag)
    await set_columns(state, T, cid, audience=f"segment:{seg}")
    await schedule(app, state, cid)
    return seg


async def _same_gen(state, cid) -> bool:
    gen = (await campaign_row(state, T, cid)).freeze_gen
    return {row.freeze_gen for row in await send_rows(state, T, cid)} == {gen}


def _refuse(monkeypatch, reason: str) -> None:
    async def refused(*_args, **_kwargs):
        raise SubscriberFilterError(reason)

    monkeypatch.setattr(freezing, "iter_subscribers", refused)


async def test_tag_audience_queues_only_tagged(built):
    app, state, cid = built
    await set_columns(state, T, cid, audience="tag:vip")
    await schedule(app, state, cid)

    assert await run_freeze(state, cid) == freezing.FreezeResult(True, 1, 0)
    assert await emails(state, cid) == [ADA]


@pytest.mark.unbound_tenant
async def test_segment_edited_after_schedule_keeps_snapshot(built):
    app, state, cid = built
    seg = await _segment_campaign(app, state, cid)
    await _edit_segment(state, seg, "events")

    assert await start_due(state) == 1
    assert await emails(state, cid) == [ADA]


async def test_segment_deleted_after_schedule_still_freezes(built):
    app, state, cid = built
    seg = await _segment_campaign(app, state, cid)
    with tenant_scope(T):
        async with state.session_factory() as db:
            await db.execute(delete(Segment).where(Segment.tenant_id == T, Segment.id == seg))
            await finalize_session(db)

    assert (await run_freeze(state, cid)).started
    assert await emails(state, cid) == [ADA]


async def test_reschedule_picks_up_new_definition(built):
    app, state, cid = built
    seg = await _segment_campaign(app, state, cid)
    await unschedule(state, cid)
    await _edit_segment(state, seg, "events")
    await schedule(app, state, cid)

    assert (await run_freeze(state, cid)).started
    assert await emails(state, cid) == [BOB]


async def test_filters_are_read_after_the_claim(built, monkeypatch):
    app, state, cid = built
    seg = await _segment_campaign(app, state, cid)
    real = freezing.claim_freeze

    async def edit_then_claim(session, **kw):
        await unschedule(state, cid)
        await _edit_segment(state, seg, "events")
        await schedule(app, state, cid)
        return await real(session, **kw)

    monkeypatch.setattr(freezing, "claim_freeze", edit_then_claim)
    assert await run_freeze(state, cid) == freezing.FreezeResult(True, 1, 0)
    assert await emails(state, cid) == [BOB]
    assert await _same_gen(state, cid)


async def test_list_switch_between_ready_and_claim_queues_only_new_list(built, monkeypatch):
    app, state, cid = built
    await seed_list(state, T, "other")
    for email in ("cy2@example.org", "dee@example.org"):
        await seed_subscriber(state, T, email, "confirmed", "other")
    await schedule(app, state, cid)  # the whole of ``tagged``: ada, bob, cy
    real = freezing.claim_freeze

    async def switch_then_claim(session, **kw):
        await unschedule(state, cid)
        revision = (await campaign_row(state, T, cid)).revision
        with tenant_scope(T):
            async with state.session_factory() as db:
                patch = CampaignPatch(expected_revision=revision, list_type_key="other")
                await drafts.update_draft(db, tenant_id=T, campaign_id=cid, patch=patch, roles=[])
                await finalize_session(db)
        await schedule(app, state, cid)
        return await real(session, **kw)

    monkeypatch.setattr(freezing, "claim_freeze", switch_then_claim)
    assert await run_freeze(state, cid) == freezing.FreezeResult(True, 2, 0)
    assert await emails(state, cid) == ["cy2@example.org", "dee@example.org"]
    assert await _same_gen(state, cid)


@pytest.mark.parametrize("stale", ["regenerated", "owner_replaced"])
async def test_stale_claim_writes_nothing(built, monkeypatch, stale):
    app, state, cid = built
    await schedule(app, state, cid)
    real = freezing.claim_freeze

    async def claim_then_lose(session, **kw):
        claim = await real(session, **kw)
        await finalize_session(session)
        if stale == "regenerated":
            await unschedule(state, cid)
            await schedule(app, state, cid)
        else:
            await set_columns(state, T, cid, freeze_owner="freeze:someone-else")
        return claim

    monkeypatch.setattr(freezing, "claim_freeze", claim_then_lose)
    assert not (await run_freeze(state, cid)).started
    assert await send_rows(state, T, cid) == []
    assert (await campaign_row(state, T, cid)).status == "scheduled"


async def test_filter_refused_pauses_audience_unavailable(built, monkeypatch):
    app, state, cid = built
    await _segment_campaign(app, state, cid)
    before = await campaign_row(state, T, cid)
    _refuse(monkeypatch, "not_indexed")

    assert not (await run_freeze(state, cid)).started
    campaign = await campaign_row(state, T, cid)
    assert (campaign.status, campaign.paused_reason) == (
        "paused",
        "audience_unavailable|not_indexed",
    )
    assert campaign.started_at is None
    assert (campaign.freeze_owner, campaign.freeze_until) == (None, None)
    assert (campaign.revision, campaign.freeze_gen) == (before.revision + 1, before.freeze_gen)
    assert await send_rows(state, T, cid) == []


async def test_reindexing_leaves_scheduled(built, monkeypatch, caplog):
    app, state, cid = built
    await _segment_campaign(app, state, cid)
    _refuse(monkeypatch, "reindexing")

    with caplog.at_level(logging.WARNING, logger=freezing.logger.name):
        assert not (await run_freeze(state, cid)).started
    assert (await campaign_row(state, T, cid)).status == "scheduled"
    assert await send_rows(state, T, cid) == []
    warnings = [r for r in caplog.records if r.name == freezing.logger.name]
    assert [r.levelname for r in warnings] == ["WARNING"]


async def test_not_a_list_pauses_list_unavailable(built, monkeypatch):
    app, state, cid = built
    await schedule(app, state, cid)
    _refuse(monkeypatch, "not_a_list")

    assert not (await run_freeze(state, cid)).started
    campaign = await campaign_row(state, T, cid)
    assert (campaign.status, campaign.paused_reason) == ("paused", "list_unavailable|")
    assert campaign.started_at is None


async def test_freeze_without_render_filters_column_value_is_all(built):
    app, state, cid = built
    await set_columns(state, T, cid, audience="tag:vip")
    await schedule(app, state, cid)
    with tenant_scope(T):
        async with state.session_factory() as db:
            await db.execute(
                update(CampaignRender)
                .where(CampaignRender.tenant_id == T, CampaignRender.campaign_id == cid)
                .values(audience_filters=[])
            )
            await finalize_session(db)

    assert (await run_freeze(state, cid)).queued == 3
    assert await emails(state, cid) == [ADA, BOB, CY]
