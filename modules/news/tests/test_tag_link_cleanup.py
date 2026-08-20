"""Deleting a tag or an article really removes its links.

``NewsArticleTag`` declares ``ondelete="CASCADE"`` on both sides, but that is a
promise the *database* keeps, and SQLite only keeps it when the connection has
run ``PRAGMA foreign_keys=ON`` — which nothing in this stack does. So on the
repo's own default database the join rows survive their parents.

A dangling row here is not inert, for exactly the reason ``NewsArticle.page_id``
is documented as dangerous: SQLite reuses ids, so an orphaned link re-attaches
to whatever tag or article is created next, and an article silently acquires a
tag nobody applied to it.
"""

from __future__ import annotations

import pytest
from conftest import make_page
from news import service, tag_service
from news.models import NewsArticle, NewsArticleTag
from pagebuilder.models import PageStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _article(db: AsyncSession, slug: str) -> NewsArticle:
    page = await make_page(db, slug=slug, status=PageStatus.PUBLISHED)
    article = NewsArticle(page_id=page.id, category="Research")
    db.add(article)
    await db.commit()
    await db.refresh(article)
    return article


async def _link_count(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(NewsArticleTag)) or 0)


async def test_deleting_a_tag_takes_its_links(db) -> None:
    article = await _article(db, "tagged")
    await tag_service.set_for_article(db, article.id or 0, ["canopy"])
    await db.flush()
    tag = (await tag_service.list_tags(db))[0]
    assert await _link_count(db) == 1

    await tag_service.delete(db, await tag_service.get(db, tag.id))

    assert await _link_count(db) == 0


async def test_detaching_an_article_takes_its_links(db) -> None:
    article = await _article(db, "detached")
    await tag_service.set_for_article(db, article.id or 0, ["canopy", "urban"])
    await db.flush()
    assert await _link_count(db) == 2

    await service.delete(db, article)

    assert await _link_count(db) == 0


async def test_the_orphan_sweep_takes_links_too(db) -> None:
    """The sweep exists because orphans re-attach; it must not leave new ones."""
    from news.maintenance import reconcile_orphans
    from pagebuilder.models import Page

    article = await _article(db, "sweep-me")
    await tag_service.set_for_article(db, article.id or 0, ["canopy"])
    await db.flush()
    page = await db.get(Page, article.page_id)
    assert page is not None
    await db.delete(page)
    await db.commit()

    dropped = await reconcile_orphans(db)

    assert dropped == 1
    assert await _link_count(db) == 0


async def test_a_surviving_articles_links_are_left_alone(db) -> None:
    """The cleanup must take only what it should."""
    kept = await _article(db, "kept")
    removed = await _article(db, "removed")
    await tag_service.set_for_article(db, kept.id or 0, ["canopy"])
    await tag_service.set_for_article(db, removed.id or 0, ["canopy"])
    await db.flush()

    await service.delete(db, removed)

    assert await tag_service.list_for_article(db, kept.id or 0) == ["canopy"]
    assert await _link_count(db) == 1
