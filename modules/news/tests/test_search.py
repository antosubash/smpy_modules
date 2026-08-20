"""Cross-section search.

What is worth pinning here is the separation: an article is a page underneath,
so the obvious implementation counts it twice and reports more results than the
archive holds.
"""

from __future__ import annotations

import pytest
from conftest import make_page
from news import search_service, service, tag_service
from pagebuilder.models import PageStatus

pytestmark = pytest.mark.asyncio

BODY = {"content": [{"type": "Heading", "props": {"text": "mixed canopy cover rose 4%"}}]}


async def _page(db, slug: str, *, title: str | None = None, draft_data: dict | None = None):
    page = await make_page(db, slug=slug, title=title or slug, status=PageStatus.PUBLISHED)
    if draft_data is not None:
        page.draft_data = draft_data
        db.add(page)
        await db.commit()
        await db.refresh(page)
    return page


async def _article(db, slug: str, *, category: str = "", title: str | None = None):
    page = await _page(db, slug, title=title)
    return await service.create(db, page_id=page.id, category=category, published_at=None)


class TestSections:
    async def test_an_empty_query_returns_nothing_not_everything(self, db) -> None:
        await _page(db, "something")

        results = await search_service.search(db, "")

        assert results.total == 0

    async def test_an_article_lands_in_articles_and_not_in_pages(self, db) -> None:
        """An article is a page underneath. Counting it in both sections would
        report more results than the archive holds."""
        await _article(db, "zephyr-article", title="Zephyr article")
        await _page(db, "zephyr-page", title="Zephyr page")

        results = await search_service.search(db, "zephyr")

        assert [h.title for h in results.articles] == ["Zephyr article"]
        assert [h.title for h in results.pages] == ["Zephyr page"]
        assert results.total == 2

    async def test_body_text_is_searched(self, db) -> None:
        await _page(db, "hidden-body", title="Nothing like the term", draft_data=BODY)

        results = await search_service.search(db, "canopy")

        assert [h.title for h in results.pages] == ["Nothing like the term"]
        assert "canopy" in results.pages[0].excerpt

    async def test_a_category_matches_its_article(self, db) -> None:
        await _article(db, "cat-match", category="Field notes", title="Unrelated title")

        results = await search_service.search(db, "field notes")

        assert [h.title for h in results.articles] == ["Unrelated title"]

    async def test_a_tag_matches_its_article(self, db) -> None:
        article = await _article(db, "tag-match", title="Also unrelated")
        await tag_service.set_for_article(db, article.id, ["canopy"])

        results = await search_service.search(db, "canopy")

        assert "Also unrelated" in [h.title for h in results.articles]

    async def test_wildcards_are_escaped(self, db) -> None:
        """Searching for `%` must not match everything."""
        await _page(db, "plain", title="Plain page")

        results = await search_service.search(db, "%")

        assert results.total == 0

    async def test_a_trashed_page_is_not_found(self, db) -> None:
        from pagebuilder.service import PagesService

        page = await _page(db, "binned", title="Binned page")
        await PagesService(db).delete(page.id)

        results = await search_service.search(db, "Binned")

        assert results.total == 0

    async def test_totals_count_beyond_the_shown_rows(self, db) -> None:
        """The "N more" affordance needs a number the list cannot supply."""
        for n in range(8):
            await _page(db, f"many-{n}", title=f"Many {n}")

        results = await search_service.search(db, "Many", per_section=5)

        assert len(results.pages) == 5
        assert results.page_total == 8
