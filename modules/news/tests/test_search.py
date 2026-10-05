"""Cross-section search.

Articles are always searched — they are this module's own. Pages and media are
searched only where pagebuilder happens to be installed, which is what
``news.integrations.pagebuilder`` now decides.

What used to be worth pinning here was that an article is a page underneath, so
the obvious implementation counted it twice and reported more results than the
archive held. That hazard is gone with the sidecar: they are two tables, and a
row can only be in one of them. What replaces it is the other shape — that the
whole screen still works with no neighbour at all.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news import search_service, tag_service
from news.integrations import pagebuilder as pb

pytestmark = pytest.mark.asyncio

BODY = {"content": [{"type": "Heading", "props": {"text": "mixed canopy cover rose 4%"}}]}

#: Pagebuilder is a workspace member here, so these run. On a host that
#: installed news alone they are skipped rather than failing — which is the
#: behaviour the split is for.
requires_pagebuilder = pytest.mark.skipif(
    not pb.available(), reason="pagebuilder is an optional extra"
)


async def _article(db, slug: str, *, category: str = "", title: str | None = None,
                   draft_data: dict | None = None):
    return await make_article(
        db, slug=slug, title=title or slug, category=category, draft_data=draft_data
    )


async def _page(db, slug: str, *, title: str | None = None, draft_data: dict | None = None):
    from pagebuilder.models import Page, PageStatus

    page = Page(
        # pagebuilder's tables are tenant-owned; news (and so this suite) is
        # not tenant-aware yet, so the row is filed where a single-tenant host's
        # pages live rather than stamped from a binding nothing here makes.
        tenant_id="default",
        slug=slug,
        title=title or slug,
        status=PageStatus.PUBLISHED,
        draft_data=draft_data or {},
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    return page


class TestArticles:
    """The section that works everywhere."""

    async def test_an_empty_query_returns_nothing_not_everything(self, db) -> None:
        await _article(db, "something")

        results = await search_service.search(db, "")

        assert results.total == 0

    async def test_a_title_matches(self, db) -> None:
        await _article(db, "zephyr-article", title="Zephyr article")

        results = await search_service.search(db, "zephyr")

        assert [h.title for h in results.articles] == ["Zephyr article"]

    async def test_a_category_matches_its_article(self, db) -> None:
        await _article(db, "cat-match", category="Field notes", title="Unrelated title")

        results = await search_service.search(db, "field notes")

        assert [h.title for h in results.articles] == ["Unrelated title"]

    async def test_a_tag_matches_its_article(self, db) -> None:
        article = await _article(db, "tag-match", title="Also unrelated")
        await tag_service.set_for_article(db, article.id, ["canopy"])

        results = await search_service.search(db, "canopy")

        assert "Also unrelated" in [h.title for h in results.articles]

    async def test_body_text_is_searched(self, db) -> None:
        """The excerpt comes from the article's own blocks now.

        It used to be read off the joined page, which is where the body lived.
        """
        await _article(db, "hidden-body", title="Nothing like the term", draft_data=BODY)

        results = await search_service.search(db, "canopy")

        assert [h.title for h in results.articles] == ["Nothing like the term"]

    async def test_wildcards_are_escaped(self, db) -> None:
        """Searching for `%` must not match everything."""
        await _article(db, "plain", title="Plain article")

        results = await search_service.search(db, "%")

        assert results.total == 0

    async def test_a_trashed_article_is_not_found(self, db) -> None:
        from news.content import ArticlesService

        article = await _article(db, "binned", title="Binned article")
        await ArticlesService(db).trash(article.id)
        await db.commit()

        assert (await search_service.search(db, "Binned")).total == 0

    async def test_a_draft_is_hidden_when_drafts_are_not_asked_for(self, db) -> None:
        from news.models import ArticleStatus

        await make_article(
            db, slug="wip", title="Draft article", status=ArticleStatus.DRAFT
        )

        results = await search_service.search(db, "Draft", include_drafts=False)

        assert results.article_total == 0

    async def test_totals_count_beyond_the_shown_rows(self, db) -> None:
        """The "N more" affordance needs a number the list cannot supply."""
        for n in range(8):
            await _article(db, f"many-{n}", title=f"Many {n}")

        results = await search_service.search(db, "Many", per_section=5)

        assert len(results.articles) == 5
        assert results.article_total == 8


@requires_pagebuilder
class TestTheOptionalSections:
    async def test_an_article_and_a_page_land_in_their_own_sections(self, db) -> None:
        """Two tables, so a row can only be in one of them.

        This assertion used to be load-bearing in a different way: an article
        *was* a page, and the pages query had to exclude every row that was one
        or the counts added up to more than the site held.
        """
        await _article(db, "zephyr-article", title="Zephyr article")
        await _page(db, "zephyr-page", title="Zephyr page")

        results = await search_service.search(db, "zephyr")

        assert [h.title for h in results.articles] == ["Zephyr article"]
        assert [h.title for h in results.pages] == ["Zephyr page"]
        assert results.total == 2

    async def test_page_body_text_is_searched(self, db) -> None:
        await _page(db, "hidden-body", title="Nothing like the term", draft_data=BODY)

        results = await search_service.search(db, "canopy")

        assert [h.title for h in results.pages] == ["Nothing like the term"]
        assert "canopy" in results.pages[0].excerpt

    async def test_a_trashed_page_is_not_found(self, db) -> None:
        from pagebuilder.service import PagesService

        page = await _page(db, "binned-page", title="Binned page")
        await PagesService(db).delete(page.id)

        assert (await search_service.search(db, "Binned page")).page_total == 0


class TestWithoutPagebuilder:
    """The host that installed news on its own.

    Simulated by making ``available()`` answer False, which is the single switch
    the integration module hangs everything off.
    """

    @pytest.fixture(autouse=True)
    def _absent(self, monkeypatch):
        monkeypatch.setattr(pb, "available", lambda: False)

    async def test_articles_are_still_searched(self, db) -> None:
        await _article(db, "solo", title="Solo article")

        results = await search_service.search(db, "solo")

        assert [h.title for h in results.articles] == ["Solo article"]

    async def test_the_page_and_media_sections_are_simply_empty(self, db) -> None:
        await _article(db, "solo", title="Solo article")

        results = await search_service.search(db, "solo")

        assert results.pages == []
        assert results.media == []
        assert results.page_total == 0
        assert results.media_total == 0
        # And the total counts only what there is, rather than reporting a
        # section the screen will not render.
        assert results.total == 1

    async def test_the_see_all_links_are_empty_rather_than_broken(self, db) -> None:
        """A link into a module that is not installed is a 404 waiting to
        happen. The screen renders no link for an empty href."""
        results = await search_service.search(db, "solo")

        assert results.pages_more_url == ""
        assert results.media_more_url == ""


@requires_pagebuilder
class TestSeeAllLinks:
    """Both "see all" links land in pagebuilder, so the server resolves them.

    The screen used to build them itself, which meant a TSX file spelling out
    how the neighbouring module routes its own page list and media library —
    exactly what ``news.integrations.pagebuilder`` exists to keep in one place.
    """

    async def test_the_pages_link_carries_the_query(self, db) -> None:
        results = await search_service.search(db, "canopy")

        assert "canopy" in results.pages_more_url

    async def test_the_media_link_is_the_library(self, db) -> None:
        assert (await search_service.search(db, "canopy")).media_more_url

    async def test_an_empty_query_still_answers_with_both_links(self, db) -> None:
        """The early return short-circuits before any query runs, so the two
        are set up front — a section that renders nothing must still not hand
        the screen an empty href."""
        results = await search_service.search(db, "")

        assert results.pages_more_url
        assert results.media_more_url
        assert results.articles == []


class TestItAgreesWithTheArticleList:
    """The console has two search boxes, and they must not disagree.

    This screen is a deliberate *superset* of the article list's own ``q``
    (``news.query_filters.search``): it adds the category and the body on top.
    What it must never do is find *less* — a row the list surfaced and this
    screen did not would read as this screen being broken.
    """

    async def test_it_finds_an_article_by_its_excerpt(self, db) -> None:
        # The field the list's `q` gained when the public archive grew a search
        # box. Without it here, one box finds the row and the other does not.
        await make_article(
            db, slug="quiet", title="Quiet", meta_description="On canopy loss."
        )

        results = await search_service.search(db, "canopy loss")

        assert [hit.title for hit in results.articles] == ["Quiet"]

    async def test_it_still_finds_more_than_the_list_does(self, db) -> None:
        # The body, which the public filter deliberately does not reach.
        await _article(db, "bodied", draft_data=BODY)

        results = await search_service.search(db, "mixed canopy")

        assert [hit.title for hit in results.articles] == ["bodied"]
