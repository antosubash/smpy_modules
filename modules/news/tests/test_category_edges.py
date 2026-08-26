"""Two ways the categories screen could be made to lie about itself.

Both are cases where a rule exists in one place and not in its mirror: the
"Uncategorised is a system name" guard lived only on create, and the article
count counted rows the listings hide.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news import category_service
from news.constants import UNCATEGORISED_LABEL
from news.content import ArticlesService
from news.models import ArticleStatus, NewsArticle
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _article(db: AsyncSession, slug: str, category: str) -> NewsArticle:
    return await make_article(db, slug=slug, category=category)


async def test_trashing_an_article_leaves_the_category_count(db) -> None:
    """The count has to match what the screen next to it will show.

    This used to trash the article's *page* — the article row stayed put and
    disappeared from the listings only because they inner-joined a page that was
    now filtered out. Trash is the article's own column now, so the test says
    what it always meant.
    """
    await _article(db, "kept", "Research")
    binned = await _article(db, "binned", "Research")

    before = await category_service.list_categories(db)
    assert {c.name: c.article_count for c in before}["Research"] == 2

    await ArticlesService(db).trash(binned.id)
    await db.commit()

    after = await category_service.list_categories(db)
    assert {c.name: c.article_count for c in after}["Research"] == 1


async def test_a_draft_still_counts(db) -> None:
    """The other half of the rule — drafts are hidden publicly but not here."""
    await make_article(db, slug="wip", status=ArticleStatus.DRAFT, category="Research")

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
