"""Where an article serves, and what serves it.

News took the *address* first: articles used to sit at ``/p/{slug}`` next to the
contact page and the privacy notice, so the URL said nothing about what the
document was. It kept borrowing the *renderer*, handing off to pagebuilder's
public viewer so the ETag, cache, CSP, canonical and redirect handling stayed in
one place rather than being duplicated and left to drift.

That trade only made sense while the body was a page. It is a column here now,
so news serves its own — and everything the hand-off used to preserve is
asserted below against this module's own viewer.

The ``TestSlugClaim`` class that used to live here is gone with the coupling it
described: news had to tell pagebuilder which slugs it no longer owned, so
``/p/{slug}`` would 404 and the sitemap would advertise the news URL. Articles
are not pages, so there is nothing to claim and no sitemap to borrow —
``TestSitemap`` covers the one news now publishes itself.
"""

from __future__ import annotations

import pytest
from conftest import make_article
from news import settings as news_settings
from news.content import ArticlesService
from news.models import ArticleStatus
from news.settings import NewsSettings

pytestmark = pytest.mark.asyncio

NEWS = "/news"


async def _seed(client, slug: str, **kwargs):
    async with client.db_state.session_factory() as db:
        return await make_article(db, slug=slug, title=slug, **kwargs)


class TestPublicPath:
    async def test_the_listing_reports_it(self, editor_client) -> None:
        await _seed(editor_client, "field-notes")

        body = (await editor_client.get("/api/news/articles")).json()

        assert body["items"][0]["url"] == "/news/field-notes"

    async def test_it_follows_the_configured_prefix(self, db) -> None:
        news_settings.use(NewsSettings(public_route_prefix="/blog"))
        from news.settings import public_article_path

        assert public_article_path("field-notes") == "/blog/field-notes"


class TestTheViewer:
    """News' own, and the reason the module can now be installed alone."""

    async def test_serves_a_published_article(self, anon_client) -> None:
        await _seed(anon_client, "published-one")

        response = await anon_client.get(f"{NEWS}/published-one")

        assert response.status_code == 200, response.text

    async def test_a_draft_is_a_404(self, anon_client) -> None:
        await _seed(anon_client, "unfinished", status=ArticleStatus.DRAFT)

        assert (await anon_client.get(f"{NEWS}/unfinished")).status_code == 404

    async def test_a_trashed_article_is_a_404(self, anon_client) -> None:
        article = await _seed(anon_client, "binned")
        async with anon_client.db_state.session_factory() as db:
            await ArticlesService(db).trash(article.id)
            await db.commit()

        assert (await anon_client.get(f"{NEWS}/binned")).status_code == 404

    async def test_a_slug_that_never_existed_is_a_404(self, anon_client) -> None:
        assert (await anon_client.get(f"{NEWS}/nothing-here")).status_code == 404

    async def test_an_article_published_without_a_body_snapshot_is_a_404(
        self, anon_client
    ) -> None:
        """``status`` alone is not enough — the viewer serves ``published_data``.

        A row marked published with nothing snapshotted would otherwise render
        an empty document at a live URL.
        """
        await _seed(anon_client, "no-snapshot", publish_body=False)

        assert (await anon_client.get(f"{NEWS}/no-snapshot")).status_code == 404

    async def test_it_serves_the_snapshot_rather_than_the_draft(
        self, anon_client
    ) -> None:
        article = await _seed(
            anon_client, "two-versions", draft_data={"content": ["live"]}
        )
        async with anon_client.db_state.session_factory() as db:
            await ArticlesService(db).save_body(article.id, {"content": ["wip"]})
            await db.commit()

        # Asked as Inertia would, so the response is the props rather than the
        # shell template — the body is what this is about.
        response = await anon_client.get(
            f"{NEWS}/two-versions", headers={"X-Inertia": "true"}
        )

        assert "live" in response.text
        assert "wip" not in response.text

    async def test_it_tells_the_body_which_article_it_is(self, anon_client) -> None:
        """The viewer hands the block document the article's own slug.

        It becomes Puck metadata, which is how a block can know what it is
        inside. ``Related`` is the block that needs it: a "read next" list that
        includes the article you are reading is visibly broken, and the slug is
        the only thing identifying the article from within its own body.
        """
        await _seed(anon_client, "knows-itself")

        response = await anon_client.get(
            f"{NEWS}/knows-itself", headers={"X-Inertia": "true"}
        )

        assert response.json()["props"]["slug"] == "knows-itself"


class TestCachingHeaders:
    """What the hand-off to pagebuilder's viewer used to guarantee."""

    async def test_it_sends_an_etag_and_cache_control(self, anon_client) -> None:
        await _seed(anon_client, "cached")

        response = await anon_client.get(f"{NEWS}/cached")

        assert response.headers["ETag"].startswith('W/"')
        assert "max-age" in response.headers["Cache-Control"]

    async def test_a_matching_etag_is_a_304(self, anon_client) -> None:
        await _seed(anon_client, "conditional")
        etag = (await anon_client.get(f"{NEWS}/conditional")).headers["ETag"]

        response = await anon_client.get(
            f"{NEWS}/conditional", headers={"If-None-Match": etag}
        )

        assert response.status_code == 304

    async def test_a_stale_etag_is_not(self, anon_client) -> None:
        await _seed(anon_client, "moved-on")

        response = await anon_client.get(
            f"{NEWS}/moved-on", headers={"If-None-Match": 'W/"nonsense"'}
        )

        assert response.status_code == 200

    async def test_no_csp_header_unless_one_is_configured(self, anon_client) -> None:
        """A module cannot know what a host's other pages already set, so the
        safe default is to send nothing rather than something restrictive."""
        await _seed(anon_client, "unpoliced")

        response = await anon_client.get(f"{NEWS}/unpoliced")

        assert "Content-Security-Policy" not in response.headers


class TestRename:
    """Renaming an article must not break the links already in the world.

    News used to read pagebuilder's redirect table, because the slug being
    renamed was a page's. It keeps its own now — same rule, its own rows.
    """

    async def test_the_old_address_forwards_to_the_new_one(self, anon_client) -> None:
        article = await _seed(anon_client, "old-name")
        async with anon_client.db_state.session_factory() as db:
            await ArticlesService(db).update(article.id, {"slug": "new-name"})
            await db.commit()

        response = await anon_client.get(f"{NEWS}/old-name")

        assert response.status_code == 301
        assert response.headers["location"] == "/news/new-name"

    async def test_a_slug_nobody_renamed_forwards_nowhere(self, anon_client) -> None:
        await _seed(anon_client, "steady")

        assert (await anon_client.get(f"{NEWS}/never-used")).status_code == 404

    async def test_renaming_back_leaves_no_redirect_loop(self, db) -> None:
        """An article reclaiming an address it once redirected away would
        otherwise send readers straight back off it."""
        from news import redirects

        article = await make_article(db, slug="first")
        service = ArticlesService(db)
        await service.update(article.id, {"slug": "second"})

        await service.update(article.id, {"slug": "first"})

        assert await redirects.resolve(db, "first") is None


class TestSitemap:
    """News advertises its own archive now.

    Articles used to reach a crawler through pagebuilder's sitemap, via the
    claim news registered with it. Without one of its own the whole archive
    would silently drop out of every index.
    """

    async def test_it_lists_published_articles(self, anon_client) -> None:
        await _seed(anon_client, "listed")

        response = await anon_client.get(f"{NEWS}/sitemap.xml")

        assert response.status_code == 200
        assert "/news/listed" in response.text

    async def test_it_omits_drafts(self, anon_client) -> None:
        await _seed(anon_client, "hidden-draft", status=ArticleStatus.DRAFT)

        assert "hidden-draft" not in (await anon_client.get(f"{NEWS}/sitemap.xml")).text

    async def test_it_omits_articles_marked_noindex(self, anon_client) -> None:
        article = await _seed(anon_client, "private")
        async with anon_client.db_state.session_factory() as db:
            await ArticlesService(db).update(article.id, {"index_in_search": False})
            await db.commit()

        assert "private" not in (await anon_client.get(f"{NEWS}/sitemap.xml")).text

    async def test_it_is_not_mistaken_for_an_article_slug(self, anon_client) -> None:
        """The route is registered before ``/{slug}`` on purpose — FastAPI
        matches in order, so the catch-all would otherwise swallow it."""
        response = await anon_client.get(f"{NEWS}/sitemap.xml")

        assert response.headers["content-type"].startswith("application/xml")
