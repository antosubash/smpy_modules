"""``/news/sitemap.xml`` — how the whole archive reaches an index.

Articles used to get there through pagebuilder's sitemap, because they were
pages in it. They are not, so news advertises its own or the archive silently
drops out of every index — which is the sort of failure nobody reports.

Split from ``test_public_archive`` when that file reached the repo's 300-line
cap, on the seam it was already leaning on: those tests are about pages a
reader browses, these about one document a crawler fetches.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news.models import ArticleStatus, NewsArticleTag, NewsCategory, NewsTag

pytestmark = pytest.mark.asyncio

NEWS = "/news"


async def _seed(client, slug: str, **kwargs):
    async with client.db_state.session_factory() as db:
        return await make_article(db, slug=slug, title=slug, **kwargs)


class TestItListsWhatLinksTheArchive:
    async def test_the_index_is_in_it_as_well_as_the_leaves(self, anon_client) -> None:
        # A sitemap of leaves tells a crawler the articles exist but not that
        # anything links them.
        await _seed(anon_client, "leaf")

        response = await anon_client.get(f"{NEWS}/sitemap.xml")

        assert f"{NEWS}/</loc>" in response.text


class TestSitemapTaxonomy:
    """The pages between the index and the leaves.

    A crawler handed only articles knows they exist but not that anything
    groups them, and ``/news/category/x`` is a real, linked, indexable page.
    An *empty* one is not: a sitemap is a request to come and index, so the
    entries are derived from the articles rather than from the taxonomy
    tables, and stop being advertised when the last article goes.
    """

    async def _category(self, client, name: str, slug: str) -> None:
        async with client.db_state.session_factory() as db:
            db.add(NewsCategory(name=name, slug=slug))
            await db.commit()

    async def _tag(self, client, article, name: str, slug: str) -> None:
        async with client.db_state.session_factory() as db:
            tag = NewsTag(name=name, slug=slug)
            db.add(tag)
            await db.flush()
            db.add(NewsArticleTag(article_id=article.id, tag_id=tag.id))
            await db.commit()

    async def test_a_category_with_a_published_article_is_listed(
        self, anon_client
    ) -> None:
        await self._category(anon_client, "Field notes", "field-notes")
        await _seed(anon_client, "in-it", category="Field notes")

        response = await anon_client.get(f"{NEWS}/sitemap.xml")

        assert f"{NEWS}/category/field-notes</loc>" in response.text

    async def test_a_category_with_nothing_published_in_it_is_not(
        self, anon_client
    ) -> None:
        # The category exists on the categories screen and its page answers
        # 200 — with nothing on it. That is a thin page, and asking a crawler
        # to come and index one is worse than saying nothing.
        await self._category(anon_client, "Empty", "empty")
        await _seed(anon_client, "elsewhere", category="Other")

        response = await anon_client.get(f"{NEWS}/sitemap.xml")

        assert "/category/empty" not in response.text

    async def test_a_draft_does_not_advertise_its_category(self, anon_client) -> None:
        await self._category(anon_client, "Pending", "pending")
        await _seed(anon_client, "unfinished", category="Pending", status=ArticleStatus.DRAFT)

        assert "/category/pending" not in (
            await anon_client.get(f"{NEWS}/sitemap.xml")
        ).text

    async def test_nor_does_an_article_held_out_of_listings(self, anon_client) -> None:
        # `show_in_feed=False` keeps the article off the archive pages, so the
        # category page it would otherwise fill renders nothing.
        await self._category(anon_client, "Standing", "standing")
        await _seed(anon_client, "standing-piece", category="Standing", show_in_feed=False)

        assert "/category/standing" not in (
            await anon_client.get(f"{NEWS}/sitemap.xml")
        ).text

    async def test_nor_does_one_that_asked_not_to_be_indexed(self, anon_client) -> None:
        # The same rule the article entries follow. A category page whose only
        # articles carry `noindex` leads a crawler nowhere it is welcome.
        await self._category(anon_client, "Quiet", "quiet")
        await _seed(anon_client, "private-piece", category="Quiet", index_in_search=False)

        assert "/category/quiet" not in (
            await anon_client.get(f"{NEWS}/sitemap.xml")
        ).text

    async def test_a_tag_carried_by_a_published_article_is_listed(
        self, anon_client
    ) -> None:
        tagged = await _seed(anon_client, "tagged")
        await self._tag(anon_client, tagged, "Canopy", "canopy")

        assert f"{NEWS}/tag/canopy</loc>" in (
            await anon_client.get(f"{NEWS}/sitemap.xml")
        ).text

    async def test_a_tag_nothing_published_carries_is_not(self, anon_client) -> None:
        draft = await _seed(anon_client, "unfinished", status=ArticleStatus.DRAFT)
        await self._tag(anon_client, draft, "Later", "later")

        assert "/tag/later" not in (await anon_client.get(f"{NEWS}/sitemap.xml")).text

    async def test_a_category_appears_once_however_many_articles_fill_it(
        self, anon_client
    ) -> None:
        # One page, one entry. Selecting it per article would list the same
        # URL as many times as the archive has stories in that category.
        await self._category(anon_client, "Field notes", "field-notes")
        await _seed(anon_client, "one", category="Field notes")
        await _seed(anon_client, "two", category="Field notes")

        response = await anon_client.get(f"{NEWS}/sitemap.xml")

        assert response.text.count(f"{NEWS}/category/field-notes</loc>") == 1


class TestANarrowedLocale:
    """Nothing deletes an article's row when its language stops being
    published. The sitemap must not keep advertising an address whose router
    was unmounted along with it — every one of these clients is English-only,
    so a row seeded directly in German (bypassing the language the running
    app was actually configured for, exactly what a ``content_locales``
    narrowing after the fact leaves behind) must not appear anywhere in it.
    """

    async def _category(self, client, name: str, slug: str) -> None:
        async with client.db_state.session_factory() as db:
            db.add(NewsCategory(name=name, slug=slug))
            await db.commit()

    async def test_the_article_itself_is_not_advertised(self, anon_client) -> None:
        await _seed(anon_client, "verlassen", locale="de")

        response = await anon_client.get(f"{NEWS}/sitemap.xml")

        assert "/de/news/verlassen" not in response.text

    async def test_nor_is_its_category_page(self, anon_client) -> None:
        await self._category(anon_client, "Nachrichten", "nachrichten")
        await _seed(anon_client, "verlassen", category="Nachrichten", locale="de")

        response = await anon_client.get(f"{NEWS}/sitemap.xml")

        assert "/de/news/category/nachrichten" not in response.text

    async def test_nor_is_its_bylines_author_page(self, anon_client) -> None:
        await _seed(anon_client, "verlassen", author="Klara Weber", locale="de")

        response = await anon_client.get(f"{NEWS}/sitemap.xml")

        assert "/de/news/author/klara-weber" not in response.text
