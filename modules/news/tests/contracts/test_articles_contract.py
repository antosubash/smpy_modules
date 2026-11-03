"""``news.contracts.articles``: published-only, tenant-pinned article cards."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from news.contracts.articles import (
    get_article_card,
    search_articles,
)
from news.core.tenancy import TenantIsolationError, tenant_scope
from news.models import ArticleStatus
from simple_module_db import tenant_context

from tests.support.factories import make_article


@pytest.fixture
async def seeded(db):
    pub = await make_article(
        db,
        slug="spring-update",
        title="Spring update",
        meta_description="Hello",
        published_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    draft = await make_article(
        db, slug="spring-draft", title="Spring draft", status=ArticleStatus.DRAFT
    )
    old = await make_article(db, slug="spring-old", title="Spring old")
    old.deleted_at = datetime(2026, 4, 2, tzinfo=UTC)
    await db.commit()
    return pub, draft, old


async def test_search_finds_published_only(db, seeded):
    pub, _, _ = seeded
    hits = await search_articles(db, tenant_id="default", pattern="%Spring%")
    assert [h.id for h in hits] == [pub.id]
    assert hits[0].path.startswith("/")
    assert "spring-update" in hits[0].path
    assert hits[0].excerpt == "Hello"
    assert hits[0].image_url == ""


@pytest.mark.unbound_tenant
async def test_search_wrong_tenant_empty(db):
    with tenant_context("default"):
        await make_article(db, slug="spring-update", title="Spring update")
    assert await search_articles(db, tenant_id="other", pattern="%Spring%") == []
    assert len(await search_articles(db, tenant_id="default", pattern="%Spring%")) == 1


async def test_card_none_for_draft_and_unknown(db, seeded):
    pub, draft, old = seeded
    assert await get_article_card(db, tenant_id="default", article_id=draft.id) is None
    assert await get_article_card(db, tenant_id="default", article_id=old.id) is None
    assert await get_article_card(db, tenant_id="default", article_id=999999) is None
    card = await get_article_card(db, tenant_id="default", article_id=pub.id)
    assert card is not None and card.title == "Spring update"


@pytest.mark.parametrize("limit", [0, 51, True])
async def test_limit_checked(db, limit):
    with pytest.raises(ValueError):
        await search_articles(db, tenant_id="default", pattern="%", limit=limit)


async def test_invalid_tenant_id_raises(db):
    with pytest.raises(ValueError):
        await search_articles(db, tenant_id="bad tenant!", pattern="%")


async def test_other_tenant_while_default_bound_raises(db, seeded):
    with pytest.raises(TenantIsolationError):
        await search_articles(db, tenant_id="other", pattern="%Spring%")
    with pytest.raises(TenantIsolationError):
        await get_article_card(db, tenant_id="other", article_id=1)


def test_tenant_scope_reenter_is_noop():
    with tenant_scope("default") as t:
        assert t == "default"
