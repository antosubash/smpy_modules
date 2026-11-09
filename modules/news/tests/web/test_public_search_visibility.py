"""Searching the public archive.

``/api/news/articles?q=`` was anonymous and the admin had a whole search screen,
but a reader browsing ``/news/`` could only page or narrow by category or tag:
the capability was built and simply not offered to the people most likely to
want it.

What these tests pin is the *shape* of the answer rather than the fact of it.
A search is an address (``/news/?q=…``), so it can be linked and paged. It
composes with everything else that narrows the archive rather than replacing
it. It obeys the archive's visibility rule, so no search reaches a draft. And
it is not indexable, because the input space is unbounded.
"""

from __future__ import annotations

import pytest
from news.models import ArticleStatus

from tests.support.public_search import _props, _seed

pytestmark = pytest.mark.asyncio

NEWS = "/news"
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}



class TestWhatASearchMayNotReach:
    async def test_a_draft_is_never_findable(self, anon_client) -> None:
        """The search box is not a back door into the visibility rule."""
        await _seed(anon_client, "secret", title="Canopy secret", status=ArticleStatus.DRAFT)

        props = await _props(anon_client, f"{NEWS}/?q=canopy")

        assert props["items"] == []

    async def test_an_article_held_out_of_listings_is_not_findable(
        self, anon_client
    ) -> None:
        await _seed(anon_client, "unlisted", title="Canopy standing page", show_in_feed=False)

        props = await _props(anon_client, f"{NEWS}/?q=canopy")

        assert props["items"] == []


class TestNoResults:
    async def test_an_empty_result_is_an_archive_not_a_404(self, anon_client) -> None:
        """The URL is meaningful — there is just nothing in it right now.

        Same reasoning as an unknown tag: a search someone linked to should say
        "nothing matches" rather than "never existed", and the page carries a
        link back to the unsearched archive.
        """
        await _seed(anon_client, "something")

        response = await anon_client.get(f"{NEWS}/?q=nothingatall", headers=INERTIA)

        assert response.status_code == 200
        props = response.json()["props"]
        assert props["items"] == []
        assert props["query"] == "nothingatall"
        # What the "way back" is built from.
        assert props["base_path"] == f"{NEWS}/"

    async def test_past_the_end_of_a_search_is_still_a_404(self, anon_client) -> None:
        # A crawler guessing ?page=900 gets told there is nothing there, rather
        # than a valid-looking empty document per query string.
        await _seed(anon_client, "something", title="Canopy")

        assert (await anon_client.get(f"{NEWS}/?q=canopy&page=9")).status_code == 404

    async def test_past_the_end_of_an_empty_archive_is_a_404_too(
        self, anon_client
    ) -> None:
        """Page 1 of an empty result is a real address. Page 2 is not."""
        assert (await anon_client.get(f"{NEWS}/?q=nothing")).status_code == 200
        assert (await anon_client.get(f"{NEWS}/?q=nothing&page=2")).status_code == 404
        assert (await anon_client.get(f"{NEWS}/tag/gone?page=2")).status_code == 404


class TestWhatACrawlerIsTold:
    async def test_results_are_noindex_follow(self, anon_client) -> None:
        """One indexed ``?q=`` link is an invitation to enumerate query strings
        forever, and every result page rearranges articles already indexed at
        their own addresses. ``follow``, though — the links out are real."""
        await _seed(anon_client, "canopy", title="Canopy")

        rendered = (await anon_client.get(f"{NEWS}/?q=canopy")).text

        assert '<meta name="robots" content="noindex,follow">' in rendered

    async def test_an_unsearched_archive_is_still_indexable(self, anon_client) -> None:
        await _seed(anon_client, "canopy")

        rendered = (await anon_client.get(f"{NEWS}/")).text

        assert 'name="robots"' not in rendered

    async def test_the_canonical_names_the_search(self, anon_client) -> None:
        for index in range(13):
            await _seed(anon_client, f"canopy-{index:02d}", title=f"Canopy {index:02d}")

        rendered = (await anon_client.get(f"{NEWS}/?q=canopy&page=2")).text

        # `q` before `page`, so one page of one search has one spelling.
        assert 'rel="canonical" href="http://test/news/?q=canopy&amp;page=2"' in rendered

    async def test_a_search_advertises_no_translations(
        self, bilingual_public_client
    ) -> None:
        """The archive pages are the same document per language; a set of
        results for an English phrase is not the German page's content."""
        await _seed(bilingual_public_client, "canopy", title="Canopy", locale="en")

        plain = (await bilingual_public_client.get(f"{NEWS}/")).text
        searched = (await bilingual_public_client.get(f"{NEWS}/?q=canopy")).text

        assert 'hreflang="de"' in plain
        assert "hreflang=" not in searched


class TestTheTermItself:
    async def test_a_blank_search_is_the_whole_archive(self, anon_client) -> None:
        # Not "nothing": a submitted-but-empty box is a reader clearing the
        # search, and answering it with an empty page would be a dead end.
        await _seed(anon_client, "first")

        props = await _props(anon_client, f"{NEWS}/?q=%20%20")

        assert [i["slug"] for i in props["items"]] == ["first"]
        assert props["query"] == ""

    async def test_an_over_long_term_is_truncated_not_rejected(
        self, anon_client
    ) -> None:
        """A 422 on a reader-facing page has nowhere to be shown."""
        response = await anon_client.get(f"{NEWS}/?q={'a' * 500}", headers=INERTIA)

        assert response.status_code == 200
        assert len(response.json()["props"]["query"]) == 100
