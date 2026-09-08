"""The archive's front door, and the feed.

Neither existed until now, and their absence was the hole in the middle of the
split. News could be installed on its own and served on its own, but the public
router had exactly one route — ``/{slug}`` — so ``/news/`` answered 404, the
bare ``/news`` bounced an anonymous visitor to the sign-in screen, and the only
browsing surface in the codebase was a block registered into *pagebuilder's*
palette. A module made independent could not be read independently.

These tests are the guard on that: every one of them fails if the front door
closes again.
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


class TestFrontDoor:
    async def test_the_index_lists_published_articles(self, anon_client) -> None:
        await _seed(anon_client, "first")
        await _seed(anon_client, "second")

        response = await anon_client.get(f"{NEWS}/", headers={"X-Inertia": "true"})

        assert response.status_code == 200
        props = response.json()["props"]
        assert {item["slug"] for item in props["items"]} == {"first", "second"}
        assert props["total"] == 2

    async def test_it_omits_drafts(self, anon_client) -> None:
        await _seed(anon_client, "live")
        await _seed(anon_client, "hidden", status=ArticleStatus.DRAFT)

        response = await anon_client.get(f"{NEWS}/", headers={"X-Inertia": "true"})

        assert [i["slug"] for i in response.json()["props"]["items"]] == ["live"]

    async def test_it_omits_articles_held_out_of_feeds(self, anon_client) -> None:
        # An article kept out of listings should not reappear in the one
        # listing that is the site's front page.
        await _seed(anon_client, "listed")
        await _seed(anon_client, "unlisted", show_in_feed=False)

        response = await anon_client.get(f"{NEWS}/", headers={"X-Inertia": "true"})

        assert [i["slug"] for i in response.json()["props"]["items"]] == ["listed"]

    async def test_an_anonymous_reader_is_not_sent_to_the_login_screen(
        self, anon_client
    ) -> None:
        """The whole point. ``/news/`` used to 404 and ``/news`` used to 302."""
        assert (await anon_client.get(f"{NEWS}/")).status_code == 200

    async def test_the_bare_prefix_is_public_too(self, anon_client) -> None:
        # A reader who trims the URL back to "/news" is asking for the archive,
        # and used to get the sign-in screen: auth runs before routing, so the
        # redirect to "/news/" never happened.
        response = await anon_client.get(NEWS, follow_redirects=False)
        assert response.status_code != 302 or "/users/login" not in response.headers.get(
            "location", ""
        )

    async def test_an_empty_archive_still_answers(self, anon_client) -> None:
        response = await anon_client.get(f"{NEWS}/", headers={"X-Inertia": "true"})
        assert response.status_code == 200
        assert response.json()["props"]["items"] == []


class TestPaging:
    async def test_it_pages(self, anon_client) -> None:
        for index in range(14):
            await _seed(anon_client, f"article-{index:02d}")

        first = await anon_client.get(f"{NEWS}/", headers={"X-Inertia": "true"})
        second = await anon_client.get(
            f"{NEWS}/?page=2", headers={"X-Inertia": "true"}
        )

        assert len(first.json()["props"]["items"]) == 12
        assert len(second.json()["props"]["items"]) == 2
        assert first.json()["props"]["pages"] == 2

    async def test_past_the_end_is_a_404(self, anon_client) -> None:
        # Rather than a valid-looking empty document for a crawler to index.
        await _seed(anon_client, "only")
        assert (await anon_client.get(f"{NEWS}/?page=9")).status_code == 404

    async def test_page_zero_is_rejected_by_the_query(self, anon_client) -> None:
        assert (await anon_client.get(f"{NEWS}/?page=0")).status_code == 422


class TestCategoryArchive:
    async def test_it_lists_only_that_category(self, anon_client) -> None:
        await _seed(anon_client, "in", category="Field notes")
        await _seed(anon_client, "out", category="Releases")
        async with anon_client.db_state.session_factory() as db:
            db.add(NewsCategory(name="Field notes", slug="field-notes"))
            await db.commit()

        response = await anon_client.get(
            f"{NEWS}/category/field-notes", headers={"X-Inertia": "true"}
        )

        props = response.json()["props"]
        assert [item["slug"] for item in props["items"]] == ["in"]
        assert props["heading"] == "Field notes"

    async def test_a_category_nobody_formalised_still_has_a_page(
        self, anon_client
    ) -> None:
        # A category typed on an article but never given a row on the categories
        # screen has no slug — the raw value has to work as one.
        await _seed(anon_client, "typed", category="Ad hoc")

        response = await anon_client.get(
            f"{NEWS}/category/Ad hoc", headers={"X-Inertia": "true"}
        )

        assert [i["slug"] for i in response.json()["props"]["items"]] == ["typed"]


class TestTagArchive:
    async def _tag(self, client, article, name: str, slug: str) -> None:
        async with client.db_state.session_factory() as db:
            tag = NewsTag(name=name, slug=slug)
            db.add(tag)
            await db.flush()
            db.add(NewsArticleTag(article_id=article.id, tag_id=tag.id))
            await db.commit()

    async def test_it_lists_only_articles_carrying_that_tag(self, anon_client) -> None:
        tagged = await _seed(anon_client, "tagged")
        await _seed(anon_client, "untagged")
        await self._tag(anon_client, tagged, "Canopy", "canopy")

        response = await anon_client.get(
            f"{NEWS}/tag/canopy", headers={"X-Inertia": "true"}
        )

        assert [i["slug"] for i in response.json()["props"]["items"]] == ["tagged"]

    async def test_an_unknown_tag_is_an_empty_archive_not_a_404(
        self, anon_client
    ) -> None:
        # A tag can be removed from the last article carrying it. The URL that
        # was published while it existed should say "nothing here now".
        await _seed(anon_client, "something")

        response = await anon_client.get(
            f"{NEWS}/tag/gone", headers={"X-Inertia": "true"}
        )

        assert response.status_code == 200
        assert response.json()["props"]["items"] == []


class TestFeed:
    async def test_it_publishes_an_rss_feed(self, anon_client) -> None:
        await _seed(anon_client, "in-the-feed", meta_description="What happened.")

        response = await anon_client.get(f"{NEWS}/feed.xml")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/rss+xml")
        assert "<rss version=\"2.0\"" in response.text
        assert f"{NEWS}/in-the-feed" in response.text
        assert "What happened." in response.text

    async def test_the_feed_omits_drafts(self, anon_client) -> None:
        await _seed(anon_client, "draft-one", status=ArticleStatus.DRAFT)
        response = await anon_client.get(f"{NEWS}/feed.xml")
        assert "draft-one" not in response.text

    async def test_it_escapes_a_headline_that_would_break_the_xml(
        self, anon_client
    ) -> None:
        async with anon_client.db_state.session_factory() as db:
            await make_article(db, slug="ampersand", title="Fish & chips <b>")

        response = await anon_client.get(f"{NEWS}/feed.xml")

        assert "Fish &amp; chips &lt;b&gt;" in response.text
        assert "<b>" not in response.text

    async def test_the_feed_is_not_mistaken_for_an_article_slug(
        self, anon_client
    ) -> None:
        # `/{slug}` matches any single segment, so registration order is what
        # keeps this from 404ing. It has been a bug once already.
        assert (await anon_client.get(f"{NEWS}/feed.xml")).status_code == 200
        assert (await anon_client.get(f"{NEWS}/sitemap.xml")).status_code == 200
