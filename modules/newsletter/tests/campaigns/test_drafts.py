"""Draft campaigns: the service, its per-list access and its optimistic writes."""

from __future__ import annotations

import asyncio

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns import access, drafts
from sm_newsletter.core.errors import (
    InvalidBody,
    ListForbidden,
    NotADraft,
    NotFound,
    StaleCampaign,
    UnknownList,
)
from sm_newsletter.core.errors_audience import InvalidAudience, SegmentListMismatch, UnknownTag
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign, Segment
from sm_newsletter.web.schemas.campaigns import CampaignCreate, CampaignPatch
from sqlalchemy import update

from tests.pg_support import make_db_state
from tests.support.records_seed import TAGS, restrict_list, seed_list

T = "default"
NOBODY: list[str] = []  # a signed-in caller holding no roles


async def _create(db, *, name: str = "Spring", key: str = "news", roles=NOBODY) -> Campaign:
    data = CampaignCreate(name=name, list_type_key=key)
    campaign = await drafts.create_draft(db, tenant_id=T, data=data, roles=roles)
    await finalize_session(db)
    return campaign


async def _patch(db, cid: int, roles=NOBODY, **fields) -> Campaign:
    patch = CampaignPatch(**fields)
    campaign = await drafts.update_draft(db, tenant_id=T, campaign_id=cid, patch=patch, roles=roles)
    await finalize_session(db)
    return campaign


async def test_create_and_read_back(db_state, db):
    await seed_list(db_state, T)
    created = await _create(db)
    assert created.status == "draft"
    assert created.revision == 1
    assert created.updated_at is not None
    got = await drafts.get_campaign(db, tenant_id=T, campaign_id=created.id, roles=NOBODY)
    assert got.name == "Spring"


async def test_create_requires_known_list(db_state, db):
    await seed_list(db_state, T)
    with pytest.raises(UnknownList):
        await _create(db, key="nope")


async def test_create_refused_for_narrowed_list(db_state, db):
    await seed_list(db_state, T, allowed_roles=["x"])
    with pytest.raises(ListForbidden):
        await _create(db, roles=[])
    assert (await _create(db, roles=["x"])).list_type_key == "news"


async def test_update_bumps_revision_and_validates_body(db_state, db):
    await seed_list(db_state, T)
    c = await _create(db)
    body = [{"type": "Divider", "props": {"id": "a"}}]
    updated = await _patch(db, c.id, expected_revision=1, subject="Hi", body=body)
    assert updated.revision == 2
    assert updated.subject == "Hi"
    assert updated.body == [{"type": "Divider", "props": {"id": "a"}}]


async def test_update_stale(db_state, db):
    await seed_list(db_state, T)
    c = await _create(db)
    await _patch(db, c.id, expected_revision=1, name="One")
    with pytest.raises(StaleCampaign):
        await _patch(db, c.id, expected_revision=1, name="Two")
    got = await drafts.get_campaign(db, tenant_id=T, campaign_id=c.id, roles=NOBODY)
    assert (got.name, got.revision) == ("One", 2)


async def _set_status(db, cid: int, status: str) -> None:
    stmt = update(Campaign).where(Campaign.id == cid, Campaign.tenant_id == T)
    await db.execute(stmt.values(status=status))
    await finalize_session(db)


async def test_update_non_draft_409(db_state, db):
    await seed_list(db_state, T)
    c = await _create(db)
    await _set_status(db, c.id, "scheduled")
    with pytest.raises(NotADraft):
        await _patch(db, c.id, expected_revision=1, name="x")


async def test_delete_non_draft_409(db_state, db):
    await seed_list(db_state, T)
    c = await _create(db)
    await _set_status(db, c.id, "scheduled")
    with pytest.raises(NotADraft):
        await drafts.delete_draft(db, tenant_id=T, campaign_id=c.id, roles=NOBODY)


async def test_delete_draft(db_state, db):
    await seed_list(db_state, T)
    c = await _create(db)
    await drafts.delete_draft(db, tenant_id=T, campaign_id=c.id, roles=NOBODY)
    await finalize_session(db)
    with pytest.raises(NotFound):
        await drafts.get_campaign(db, tenant_id=T, campaign_id=c.id, roles=NOBODY)
    with pytest.raises(NotFound):
        await drafts.delete_draft(db, tenant_id=T, campaign_id=c.id, roles=NOBODY)


@pytest.mark.unbound_tenant
async def test_other_tenant_not_found(db_state):
    for tenant in ("a", "b"):
        await seed_list(db_state, tenant)
    with tenant_scope("a"):
        async with db_state.session_factory() as db:
            data = CampaignCreate(name="A", list_type_key="news")
            c = await drafts.create_draft(db, tenant_id="a", data=data, roles=NOBODY)
            await finalize_session(db)
    with tenant_scope("b"):
        async with db_state.session_factory() as db:
            with pytest.raises(NotFound):
                await drafts.get_campaign(db, tenant_id="b", campaign_id=c.id, roles=NOBODY)
            patch = CampaignPatch(expected_revision=1, name="stolen")
            with pytest.raises(NotFound):
                await drafts.update_draft(
                    db, tenant_id="b", campaign_id=c.id, patch=patch, roles=NOBODY
                )
            with pytest.raises(NotFound):
                await drafts.delete_draft(db, tenant_id="b", campaign_id=c.id, roles=NOBODY)
            items, total = await drafts.list_campaigns(
                db, tenant_id="b", roles=NOBODY, status=None, q=None, offset=0, limit=50
            )
            assert (items, total) == ([], 0)


async def test_audience_validated_on_patch(db_state, db):
    await seed_list(db_state, T, fields=[TAGS])
    await seed_list(db_state, T, "other", fields=[TAGS])
    c = await _create(db)
    with tenant_scope(T):
        seg = Segment(tenant_id=T, name="o", list_type_key="other", filters=["tags:in:vip"])
        db.add(seg)
        await finalize_session(db)
    assert (await _patch(db, c.id, expected_revision=1, audience="tag:vip")).audience == "tag:vip"
    with pytest.raises(UnknownTag):
        await _patch(db, c.id, expected_revision=2, audience="tag:nope")
    with pytest.raises(SegmentListMismatch):
        await _patch(db, c.id, expected_revision=2, audience=f"segment:{seg.id}")
    with pytest.raises(InvalidAudience):
        await _patch(db, c.id, expected_revision=2, audience="segment:012")
    own = Segment(tenant_id=T, name="n", list_type_key="news", filters=["tags:in:vip"])
    with tenant_scope(T):
        db.add(own)
        await finalize_session(db)
    moved = await _patch(db, c.id, expected_revision=2, audience=f"segment:{own.id}")
    assert moved.revision == 3
    # Moving the list under a segment of the old one is refused, and nothing is written.
    with pytest.raises(SegmentListMismatch):
        await _patch(db, c.id, expected_revision=3, list_type_key="other")
    row = await drafts.get_campaign(db, tenant_id=T, campaign_id=c.id, roles=NOBODY)
    assert (row.list_type_key, row.audience, row.revision) == ("news", f"segment:{own.id}", 3)


async def test_body_validated(db_state, db):
    await seed_list(db_state, T)
    c = await _create(db)
    with pytest.raises(InvalidBody):
        await _patch(db, c.id, expected_revision=1, body=[{"type": "Video", "props": {"id": "a"}}])
    got = await drafts.get_campaign(db, tenant_id=T, campaign_id=c.id, roles=NOBODY)
    assert (got.body, got.revision) == ([], 1)


async def test_change_list_checks_access(db_state, db):
    await seed_list(db_state, T)
    await seed_list(db_state, T, "vip", allowed_roles=["x"])
    c = await _create(db)
    with pytest.raises(UnknownList):
        await _patch(db, c.id, expected_revision=1, list_type_key="nope")
    with pytest.raises(ListForbidden):
        await _patch(db, c.id, expected_revision=1, list_type_key="vip")
    moved = await _patch(db, c.id, roles=["x"], expected_revision=1, list_type_key="vip")
    assert moved.list_type_key == "vip"


async def test_list_orders_filters_and_counts(db_state, db):
    await seed_list(db_state, T)
    await seed_list(db_state, T, "vip", allowed_roles=["x"])
    first = await _create(db, name="Alpha 100%")
    second = await _create(db, name="Beta")
    await _create(db, name="Hidden", key="vip", roles=["x"])
    await _patch(db, first.id, expected_revision=1, subject="touched")

    def ids(items):
        return [c.id for c in items]

    async def page(**kw):
        args = {"status": None, "q": None, "offset": 0, "limit": 50, "roles": NOBODY, **kw}
        return await drafts.list_campaigns(db, tenant_id=T, **args)

    items, total = await page()
    assert (ids(items), total) == ([first.id, second.id], 2)
    items, total = await page(roles=["x"])
    assert total == 3
    items, total = await page(q="100%")
    assert ids(items) == [first.id]
    assert (await page(q="_"))[1] == 0  # escaped, not a wildcard
    assert (await page(status="sent"))[1] == 0
    items, total = await page(offset=1, limit=1)
    assert (ids(items), total) == ([second.id], 2)


async def test_restricted_list_hides_its_campaigns(db_state, db):
    await seed_list(db_state, T)
    c = await _create(db)
    await restrict_list(db_state, T, "news", ["x"])
    assert await access.readable_lists(db, tenant_id=T, roles=NOBODY) == []
    with pytest.raises(NotFound):
        await drafts.get_campaign(db, tenant_id=T, campaign_id=c.id, roles=NOBODY)
    with pytest.raises(NotFound):
        await _patch(db, c.id, expected_revision=1, name="x")
    with pytest.raises(NotFound):
        await drafts.delete_draft(db, tenant_id=T, campaign_id=c.id, roles=NOBODY)
    assert (
        await drafts.list_campaigns(
            db, tenant_id=T, roles=NOBODY, status=None, q=None, offset=0, limit=50
        )
    )[1] == 0
    assert await access.readable_lists(db, tenant_id=T, roles=["x"]) == ["news"]


async def test_concurrent_patches_exactly_one_wins(tmp_path):
    """Two sessions, one connection each, the same ``expected_revision``."""
    state = await make_db_state(file=tmp_path / "race.db")
    try:
        await seed_list(state, T)
        async with state.session_factory() as db:
            c = await _create(db)

        async def attempt(name: str) -> str:
            async with state.session_factory() as db:
                try:
                    await _patch(db, c.id, expected_revision=1, name=name)
                except StaleCampaign:
                    return "stale"
                return "won"

        outcomes = await asyncio.gather(attempt("left"), attempt("right"))
        assert sorted(outcomes) == ["stale", "won"]
        async with state.session_factory() as db:
            got = await drafts.get_campaign(db, tenant_id=T, campaign_id=c.id, roles=NOBODY)
            assert got.revision == 2
            assert got.name == ("left" if outcomes[0] == "won" else "right")
    finally:
        await state.engine.dispose()
