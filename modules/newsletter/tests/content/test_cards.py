"""Card snapshots and the server-side refresh (ruling R9, amendment 2)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns import drafts
from sm_newsletter.content import cards
from sm_newsletter.content.blocks import CardProps
from sm_newsletter.content.integrations import CardHit, like_pattern
from sm_newsletter.core.errors import (
    BlockNotFound,
    CardSourceGone,
    NotADraft,
    StaleCampaign,
)
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign
from sm_newsletter.web.schemas.campaigns import CampaignCreate, CampaignPatch
from sqlalchemy import update

from tests.pg_support import make_db_state
from tests.support.news_seed import UNPUBLISHED, change_article, seed_article
from tests.support.records_seed import seed_list

T = "default"
NOBODY: list[str] = []
APP = SimpleNamespace(state=SimpleNamespace(news=object()))


async def _campaign_with_card(db_state, db, article_id: int) -> tuple[Campaign, dict]:
    await seed_list(db_state, T)
    c = await drafts.create_draft(
        db, tenant_id=T, data=CampaignCreate(name="S", list_type_key="news"), roles=NOBODY
    )
    await finalize_session(db)
    props = await cards.snapshot(APP, db, tenant_id=T, kind="article", source_id=article_id)
    body = [
        {"type": "Divider", "props": {"id": "div"}},
        {"type": "ArticleCard", "props": props},
    ]
    patch = CampaignPatch(expected_revision=1, body=body)
    c = await drafts.update_draft(db, tenant_id=T, campaign_id=c.id, patch=patch, roles=NOBODY)
    await finalize_session(db)
    return c, props


async def _refresh(db, cid: int, block_id: str, revision: int) -> Campaign:
    campaign = await cards.refresh_block(
        APP,
        db,
        tenant_id=T,
        campaign_id=cid,
        block_id=block_id,
        expected_revision=revision,
        roles=NOBODY,
    )
    await finalize_session(db)
    return campaign


async def test_snapshot_article_from_contract(db_state, db):
    aid = await seed_article(db_state, T, og_image="/media/cover.png")
    props = await cards.snapshot(APP, db, tenant_id=T, kind="article", source_id=aid)
    assert len(props["id"]) == 12
    assert props["source_id"] == aid
    assert (props["title"], props["excerpt"]) == ("Spring update", "Hello")
    assert props["url"].startswith("/") and "spring-update" in props["url"]
    assert props["image_url"] == "/media/cover.png"
    CardProps.model_validate(props)  # what the body accepts
    other = await cards.snapshot(APP, db, tenant_id=T, kind="article", source_id=aid)
    assert other["id"] != props["id"]


def test_snapshot_props_fits_the_block():
    hit = CardHit(
        kind="article",
        source_id=3,
        title="t" * 400,
        excerpt="e" * 2000,
        image_url="javascript:alert(1)",
        url="/n/x",
        locale="en",
    )
    now = datetime(2026, 11, 5, tzinfo=UTC)
    props = cards.snapshot_props(hit, block_id="abc", now=now)
    assert (len(props["title"]), len(props["excerpt"])) == (300, 1000)
    assert props["image_url"] == ""
    assert datetime.fromisoformat(props["snapshot_at"]) == now
    CardProps.model_validate(props)


async def test_refresh_updates_title(db_state, db):
    aid = await seed_article(db_state, T)
    c, props = await _campaign_with_card(db_state, db, aid)
    rev = c.revision
    await change_article(db_state, T, aid, title="Summer update")
    refreshed = await _refresh(db, c.id, props["id"], rev)
    assert refreshed.revision == rev + 1
    card = refreshed.body[1]
    assert card["props"]["id"] == props["id"]
    assert card["props"]["title"] == "Summer update"
    assert card["props"]["snapshot_at"] >= props["snapshot_at"]
    assert refreshed.body[0] == {"type": "Divider", "props": {"id": "div"}}


async def _assert_gone_and_kept(db, cid: int, block_id: str) -> None:
    before = await drafts.get_campaign(db, tenant_id=T, campaign_id=cid, roles=NOBODY)
    kept = (before.revision, before.body)
    with pytest.raises(CardSourceGone):
        await _refresh(db, cid, block_id, kept[0])
    await db.rollback()
    after = await drafts.get_campaign(db, tenant_id=T, campaign_id=cid, roles=NOBODY)
    assert (after.revision, after.body) == kept


@pytest.mark.parametrize("how", ["unpublished", "trashed"])
async def test_refresh_unpublished_is_gone_and_keeps_snapshot(db_state, db, how):
    aid = await seed_article(db_state, T)
    c, props = await _campaign_with_card(db_state, db, aid)
    if how == "unpublished":
        await change_article(db_state, T, aid, status=UNPUBLISHED)
    else:
        await change_article(db_state, T, aid, deleted_at=datetime(2026, 5, 1, tzinfo=UTC))
    await _assert_gone_and_kept(db, c.id, props["id"])


@pytest.mark.unbound_tenant
async def test_refresh_other_tenants_article_is_gone(db_state, db):
    """A card naming another tenant's published article: gone, not read."""
    theirs = await seed_article(db_state, "other", slug="theirs")
    with tenant_scope(T):
        aid = await seed_article(db_state, T)
        c, props = await _campaign_with_card(db_state, db, aid)
        card = {"type": "ArticleCard", "props": {**props, "source_id": theirs}}
        stmt = update(Campaign).where(Campaign.id == c.id).values(body=[c.body[0], card])
        await db.execute(stmt)
        await finalize_session(db)
        await _assert_gone_and_kept(db, c.id, props["id"])


async def test_refresh_non_card_404(db_state, db):
    aid = await seed_article(db_state, T)
    c, _ = await _campaign_with_card(db_state, db, aid)
    with pytest.raises(BlockNotFound):
        await _refresh(db, c.id, "div", c.revision)
    with pytest.raises(BlockNotFound):
        await _refresh(db, c.id, "missing", c.revision)


async def test_refresh_refuses_stale_and_non_draft(db_state, db):
    aid = await seed_article(db_state, T)
    c, props = await _campaign_with_card(db_state, db, aid)
    cid, rev = c.id, c.revision
    with pytest.raises(StaleCampaign):
        await _refresh(db, cid, props["id"], rev - 1)
    await db.rollback()
    await db.execute(update(Campaign).where(Campaign.id == cid).values(status="sent"))
    await finalize_session(db)
    with pytest.raises(NotADraft):
        await _refresh(db, cid, props["id"], rev)


async def test_concurrent_patch_and_refresh_exactly_one_wins(tmp_path):
    """Two sessions, one connection each, the same ``expected_revision``."""
    state = await make_db_state(file=tmp_path / "race.db")
    try:
        aid = await seed_article(state, T)
        async with state.session_factory() as db:
            c, props = await _campaign_with_card(state, db, aid)
        await change_article(state, T, aid, title="Summer update")

        async def patch() -> str:
            async with state.session_factory() as db:
                p = CampaignPatch(expected_revision=c.revision, name="patched")
                try:
                    await drafts.update_draft(
                        db, tenant_id=T, campaign_id=c.id, patch=p, roles=NOBODY
                    )
                    await finalize_session(db)
                except StaleCampaign:
                    return "stale"
                return "won"

        async def refresh() -> str:
            async with state.session_factory() as db:
                try:
                    await _refresh(db, c.id, props["id"], c.revision)
                except StaleCampaign:
                    return "stale"
                return "won"

        outcomes = await asyncio.gather(patch(), refresh())
        assert sorted(outcomes) == ["stale", "won"]
        async with state.session_factory() as db:
            got = await drafts.get_campaign(db, tenant_id=T, campaign_id=c.id, roles=NOBODY)
        assert got.revision == c.revision + 1
        if outcomes[0] == "won":
            assert (got.name, got.body[1]["props"]["title"]) == ("patched", "Spring update")
        else:
            assert (got.name, got.body[1]["props"]["title"]) == ("S", "Summer update")
    finally:
        await state.engine.dispose()


@pytest.mark.parametrize(
    ("q", "pattern"),
    [
        ("spring", "%spring%"),
        ("  50%_off\\ ", "%50\\%\\_off\\\\%"),
        ("", "%%"),
        ("x" * 150, "%" + "x" * 100 + "%"),
    ],
)
def test_like_pattern_escapes(q, pattern):
    assert like_pattern(q) == pattern
