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
from news.integrations import pagebuilder as pb
from news.web.services import search_service
from simple_module_db import tenant_context

from tests.support.search import _article, _page

pytestmark = pytest.mark.asyncio

BODY = {"content": [{"type": "Heading", "props": {"text": "mixed canopy cover rose 4%"}}]}

#: Pagebuilder is a workspace member here, so these run. On a host that
#: installed news alone they are skipped rather than failing — which is the
#: behaviour the split is for.
requires_pagebuilder = pytest.mark.skipif(
    not pb.available(), reason="pagebuilder is an optional extra"
)



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
@pytest.mark.unbound_tenant
async def test_another_tenants_page_is_not_searched(db) -> None:
    """A single-tenant request binds the default tenant, under which
    pagebuilder's tables are not filtered at all; the search pins itself to it
    rather than listing every one. Nothing bound is refused —
    ``test_search_tenancy`` (#210)."""
    await _page(db, "ours-zircon", title="Zircon ours")
    await _page(db, "theirs-zircon", title="Zircon theirs", tenant="other")

    with tenant_context("default"):
        hits, total = await pb.search_pages(db, "%zircon%", include_drafts=True, limit=10)

    assert [p.title for p in hits] == ["Zircon ours"]
    assert total == 1
