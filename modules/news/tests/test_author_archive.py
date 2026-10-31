"""The byline, and where it goes.

``author`` was a column, rendered on the article and emitted as
``article:author``, with no route behind it: a category and a tag each had an
archive and the person who wrote the piece did not, so a reader who liked a
writer had nowhere to go.

The interesting part is that ``author`` is free text with no managed row, so the
address is *derived* from the byline rather than read off a slug column. These
tests pin the two consequences that follow — two spellings share one page, and a
byline with nothing to slugify has no page at all — because they are what would
otherwise be discovered by someone reading a wrong archive.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio

NEWS = "/news"
INERTIA = {"X-Inertia": "true"}


async def _seed(client, slug: str, **kwargs):
    kwargs.setdefault("title", slug)
    async with client.db_state.session_factory() as db:
        return await make_article(db, slug=slug, **kwargs)


async def _props(client, path: str) -> dict:
    response = await client.get(path, headers=INERTIA)
    assert response.status_code == 200, response.text
    return response.json()["props"]


class TestTheArchive:
    async def test_it_lists_that_author(self, anon_client) -> None:
        await _seed(anon_client, "theirs", author="Anto Subash")
        await _seed(anon_client, "someone-elses", author="Jane Doe")

        props = await _props(anon_client, f"{NEWS}/author/anto-subash")

        assert [i["slug"] for i in props["items"]] == ["theirs"]
        assert props["heading"] == "Anto Subash"

    async def test_it_omits_drafts(self, anon_client) -> None:
        await _seed(anon_client, "live", author="Anto Subash")
        await _seed(
            anon_client, "hidden", author="Anto Subash", status=ArticleStatus.DRAFT
        )

        props = await _props(anon_client, f"{NEWS}/author/anto-subash")

        assert [i["slug"] for i in props["items"]] == ["live"]

    async def test_it_omits_articles_held_out_of_listings(self, anon_client) -> None:
        await _seed(anon_client, "listed", author="Anto Subash")
        await _seed(anon_client, "unlisted", author="Anto Subash", show_in_feed=False)

        props = await _props(anon_client, f"{NEWS}/author/anto-subash")

        assert [i["slug"] for i in props["items"]] == ["listed"]

    async def test_an_unknown_byline_is_an_empty_archive_not_a_404(
        self, anon_client
    ) -> None:
        """Same rule as an unknown tag: a byline can be edited off the last
        article carrying it, and the URL published while it existed should say
        "nothing here now"."""
        await _seed(anon_client, "something", author="Anto Subash")

        response = await anon_client.get(f"{NEWS}/author/nobody", headers=INERTIA)

        assert response.status_code == 200
        assert response.json()["props"]["items"] == []

    async def test_an_unknown_byline_does_not_list_the_whole_archive(
        self, anon_client
    ) -> None:
        """The failure the empty-list filter exists to prevent: an address
        nobody has published under must narrow to nothing, not to everything."""
        await _seed(anon_client, "a", author="Anto Subash")
        await _seed(anon_client, "b", author="")

        props = await _props(anon_client, f"{NEWS}/author/nobody")

        assert props["items"] == []
        assert props["total"] == 0

    async def test_it_pages(self, anon_client) -> None:
        for index in range(14):
            await _seed(anon_client, f"piece-{index:02d}", author="Anto Subash")

        first = await _props(anon_client, f"{NEWS}/author/anto-subash")
        second = await _props(anon_client, f"{NEWS}/author/anto-subash?page=2")

        assert len(first["items"]) == 12
        assert len(second["items"]) == 2

    async def test_a_search_narrows_within_the_byline(self, anon_client) -> None:
        await _seed(anon_client, "canopy", title="Canopy cover", author="Anto Subash")
        await _seed(anon_client, "budget", title="The budget", author="Anto Subash")

        props = await _props(anon_client, f"{NEWS}/author/anto-subash?q=canopy")

        assert [i["slug"] for i in props["items"]] == ["canopy"]
        assert props["narrowed"] is True


class TestCollidingSpellings:
    """Two spellings of one byline slug the same, and share one page.

    Deliberate, and the reason this needs no table. A byline entered two ways is
    overwhelmingly one person entered inconsistently, so an address that served
    one spelling and hid the other would lose a reader exactly the articles they
    came for.
    """

    async def test_both_spellings_are_listed(self, anon_client) -> None:
        await _seed(anon_client, "dotted", author="A. Subash")
        await _seed(anon_client, "undotted", author="A Subash")

        props = await _props(anon_client, f"{NEWS}/author/a-subash")

        assert {i["slug"] for i in props["items"]} == {"dotted", "undotted"}

    async def test_the_page_is_titled_with_the_majority_spelling(
        self, anon_client
    ) -> None:
        await _seed(anon_client, "one", author="A Subash")
        await _seed(anon_client, "two", author="A Subash")
        await _seed(anon_client, "three", author="A. Subash")

        props = await _props(anon_client, f"{NEWS}/author/a-subash")

        assert props["heading"] == "A Subash"


class TestOneLanguageOnly:
    async def test_it_lists_the_language_it_is_mounted_under(
        self, bilingual_public_client
    ) -> None:
        client = bilingual_public_client
        await _seed(client, "english", author="Anto Subash", locale="en")
        await _seed(client, "german", author="Anto Subash", locale="de")

        english = await _props(client, f"{NEWS}/author/anto-subash")
        german = await _props(client, f"/de{NEWS}/author/anto-subash")

        assert [i["slug"] for i in english["items"]] == ["english"]
        assert [i["slug"] for i in german["items"]] == ["german"]

    async def test_an_author_who_writes_in_one_language_is_empty_in_the_other(
        self, bilingual_public_client
    ) -> None:
        client = bilingual_public_client
        await _seed(client, "german-only", author="Klara Weber", locale="de")

        props = await _props(client, f"{NEWS}/author/klara-weber")

        assert props["items"] == []


class TestTheBylineOnTheArticle:
    async def test_the_byline_links_to_its_archive(self, anon_client) -> None:
        """The dead end this closes."""
        await _seed(anon_client, "piece", author="Anto Subash")

        props = await _props(anon_client, f"{NEWS}/piece")

        assert props["author_url"] == f"{NEWS}/author/anto-subash"

    async def test_a_byline_with_no_address_is_not_linked(self, anon_client) -> None:
        await _seed(anon_client, "piece", author="田中太郎")

        assert (await _props(anon_client, f"{NEWS}/piece"))["author_url"] is None

    async def test_an_unattributed_article_has_no_link(self, anon_client) -> None:
        await _seed(anon_client, "piece")

        assert (await _props(anon_client, f"{NEWS}/piece"))["author_url"] is None

    async def test_an_unlisted_articles_own_byline_is_not_linked(self, anon_client) -> None:
        """The article is real and publicly readable — ``show_in_feed=False``
        holds it out of listings, not out of the site — but it is the only
        piece by this byline, so the archive it would link to has nothing in
        it. Linking there would send a reader to a page titled with the raw
        slug and no articles, worse than the plain text this renders instead.
        """
        await _seed(anon_client, "piece", author="Anto Subash", show_in_feed=False)

        assert (await _props(anon_client, f"{NEWS}/piece"))["author_url"] is None

    async def test_a_german_article_links_to_the_german_archive(
        self, bilingual_public_client
    ) -> None:
        await _seed(bilingual_public_client, "stueck", author="Klara Weber", locale="de")

        props = await _props(bilingual_public_client, f"/de{NEWS}/stueck")

        assert props["author_url"] == f"/de{NEWS}/author/klara-weber"


class TestTheSitemap:
    """Same gate as the category and tag pages: at least one published,
    indexable, listed article in that language."""

    async def _sitemap(self, client) -> str:
        response = await client.get(f"{NEWS}/sitemap.xml")
        assert response.status_code == 200
        return response.text

    async def test_an_author_with_a_published_article_is_listed(
        self, anon_client
    ) -> None:
        await _seed(anon_client, "piece", author="Anto Subash")

        assert "<loc>http://test/news/author/anto-subash</loc>" in await self._sitemap(
            anon_client
        )

    async def test_a_draft_only_author_is_not(self, anon_client) -> None:
        await _seed(
            anon_client, "piece", author="Anto Subash", status=ArticleStatus.DRAFT
        )

        assert "author/anto-subash" not in await self._sitemap(anon_client)

    async def test_a_noindex_only_author_is_not(self, anon_client) -> None:
        # An empty-in-the-index page is a thin page, and a sitemap is a request
        # to come and index.
        await _seed(anon_client, "piece", author="Anto Subash", index_in_search=False)

        assert "author/anto-subash" not in await self._sitemap(anon_client)

    async def test_an_unlisted_only_author_is_not(self, anon_client) -> None:
        await _seed(anon_client, "piece", author="Anto Subash", show_in_feed=False)

        assert "author/anto-subash" not in await self._sitemap(anon_client)

    async def test_a_byline_with_no_address_is_not_advertised(
        self, anon_client
    ) -> None:
        await _seed(anon_client, "piece", author="田中太郎")

        assert "/news/author/" not in await self._sitemap(anon_client)

    async def test_colliding_spellings_are_advertised_once(self, anon_client) -> None:
        await _seed(anon_client, "dotted", author="A. Subash")
        await _seed(anon_client, "undotted", author="A Subash")

        assert (await self._sitemap(anon_client)).count(
            "<loc>http://test/news/author/a-subash</loc>"
        ) == 1

    async def test_each_language_gets_its_own_entry(
        self, bilingual_public_client
    ) -> None:
        client = bilingual_public_client
        await _seed(client, "english", author="Anto Subash", locale="en")
        await _seed(client, "german", author="Anto Subash", locale="de")

        text = await self._sitemap(client)

        assert "<loc>http://test/news/author/anto-subash</loc>" in text
        assert "<loc>http://test/de/news/author/anto-subash</loc>" in text
