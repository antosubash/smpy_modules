"""Two ways the categories screen could be made to lie about itself.

Both are cases where a rule exists in one place and not in its mirror: the
"Uncategorised is a system name" guard lived only on create, and the article
count counted rows the listings hide.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import make_page
from news import category_service
from news.constants import UNCATEGORISED_LABEL
from news.models import NewsArticle
from pagebuilder.models import Page, PageStatus
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _article(db: AsyncSession, slug: str, category: str) -> NewsArticle:
    page = await make_page(db, slug=slug, status=PageStatus.PUBLISHED)
    article = NewsArticle(page_id=page.id, category=category)
    db.add(article)
    await db.commit()
    await db.refresh(article)
    return article


async def test_a_trashed_articles_page_leaves_the_category_count(db) -> None:
    """The count has to match what the screen next to it will show."""
    await _article(db, "kept", "Research")
    binned = await _article(db, "binned", "Research")

    before = await category_service.list_categories(db)
    assert {c.name: c.article_count for c in before}["Research"] == 2

    page = await db.get(Page, binned.page_id)
    assert page is not None
    page.deleted_at = datetime.now(UTC)
    db.add(page)
    await db.commit()

    after = await category_service.list_categories(db)
    assert {c.name: c.article_count for c in after}["Research"] == 1


async def test_a_draft_still_counts(db) -> None:
    """The other half of the rule — drafts are hidden publicly but not here."""
    page = await make_page(db, slug="wip", status=PageStatus.DRAFT)
    db.add(NewsArticle(page_id=page.id, category="Research"))
    await db.commit()

    counts = {c.name: c.article_count for c in await category_service.list_categories(db)}

    assert counts["Research"] == 1


async def test_a_category_cannot_be_renamed_into_the_system_name(
    editor_client,
) -> None:
    """Creating it is refused; renaming into it has to be refused too."""
    created = await editor_client.post(
        "/api/news/taxonomy/categories", json={"name": "Research"}
    )
    assert created.status_code == 201, created.text
    category_id = created.json()["id"]

    renamed = await editor_client.put(
        f"/api/news/taxonomy/categories/{category_id}",
        json={"name": UNCATEGORISED_LABEL},
    )

    assert renamed.status_code == 409, renamed.text

    listed = await editor_client.get("/api/news/taxonomy/categories")
    names = [c["name"] for c in listed.json()["items"]]
    assert names.count(UNCATEGORISED_LABEL) == 1


async def test_the_system_name_is_still_refused_on_create(editor_client) -> None:
    refused = await editor_client.post(
        "/api/news/taxonomy/categories", json={"name": UNCATEGORISED_LABEL.lower()}
    )

    assert refused.status_code == 409, refused.text
