"""Where an article actually serves.

Articles used to share pagebuilder's generic page prefix, so every one of them
sat at ``/p/{slug}`` next to the contact page and the privacy notice — the
address said nothing about what the document was, and nothing could tell an
article from a page in a URL, a log line or an analytics report.

They have their own prefix now. Claiming an address means giving it up
elsewhere, so these cover both halves: the news URL is what the API reports,
and pagebuilder is told which slugs it no longer owns.
"""

from __future__ import annotations

import pytest
from conftest import make_page
from news import service
from news import settings as news_settings
from news.endpoints.public_views import published_article_slugs, slug_claim
from news.integrations.pagebuilder import PageStatus
from news.settings import NewsSettings

pytestmark = pytest.mark.asyncio


async def _record_redirect(db, *, page_id: int, old: str, new: str) -> None:
    from pagebuilder import redirects

    await redirects.record(
        db, page_id=page_id, old_slug=old, new_slug=new, locale="en"
    )


async def _article(db, slug: str, *, status: PageStatus = PageStatus.PUBLISHED):
    page = await make_page(db, slug=slug, title=slug, status=status)
    await service.create(db, page_id=page.id, category="", published_at=None)
    await db.commit()
    return page


class TestPublicPath:
    async def test_the_listing_reports_it(self, editor_client) -> None:
        async with editor_client.db_state.session_factory() as db:
            await _article(db, "field-notes")

        body = (await editor_client.get("/api/news/articles")).json()

        assert body["items"][0]["url"] == "/news/field-notes"


class TestWhichSlugsAreArticles:
    """The query behind both the viewer and the claim, so a page that is not an
    article keeps its own address and a draft never leaks one."""

    async def test_finds_a_published_article(self, db) -> None:
        await _article(db, "published-one")

        assert await published_article_slugs(db, ["published-one"]) == {"published-one"}

    async def test_a_plain_page_is_not_one(self, db) -> None:
        await make_page(db, slug="contact", title="Contact")
        await db.commit()

        assert await published_article_slugs(db, ["contact"]) == set()

    async def test_a_draft_article_is_not_one(self, db) -> None:
        # It has no public address yet, so pagebuilder must not be told the
        # slug is taken — and the viewer must not serve it.
        await _article(db, "unfinished", status=PageStatus.DRAFT)

        assert await published_article_slugs(db, ["unfinished"]) == set()

    async def test_answers_the_whole_set_in_one_go(self, db) -> None:
        """Bulk on purpose: the sitemap asks about every published page at once,
        and a per-slug lookup would make a crawl as many round trips deep as the
        site has pages."""
        await _article(db, "one")
        await _article(db, "two")
        await make_page(db, slug="three", title="Three")
        await db.commit()

        assert await published_article_slugs(db, ["one", "two", "three"]) == {"one", "two"}

    async def test_an_empty_ask_never_queries(self, db) -> None:
        assert await published_article_slugs(db, []) == set()


class TestSlugClaim:
    """What pagebuilder is handed. It makes /p/{slug} 404 for these slugs and
    puts the news URL in the sitemap instead."""

    async def test_maps_articles_to_their_news_url(self, db) -> None:
        await _article(db, "field-notes")
        await make_page(db, slug="contact", title="Contact")
        await db.commit()

        assert await slug_claim()(db, ["field-notes", "contact"], "en") == {
            "field-notes": "/news/field-notes"
        }

    async def test_agrees_with_what_the_api_reports(self, db) -> None:
        """The address a crawler is sent to and the address the admin list
        shows are the same string, or one of them is a 404."""
        page = await _article(db, "field-notes")
        read = await service.get_read_by_page(db, page.id)

        claimed = await slug_claim()(db, ["field-notes"], "en")

        assert claimed["field-notes"] == read.url

    async def test_follows_the_configured_prefix(self, db) -> None:
        await _article(db, "field-notes")
        news_settings.use(NewsSettings(public_route_prefix="/blog"))

        assert await slug_claim()(db, ["field-notes"], "en") == {"field-notes": "/blog/field-notes"}


class TestRename:
    """Renaming an article must behave like renaming any other page.

    Pagebuilder records a redirect for the old slug because the old URL is
    already in bookmarks, in links from other sites, and in a search index that
    has not recrawled. The news address reads the same table rather than
    keeping its own.
    """

    async def test_the_old_address_forwards_to_the_new_one(self, db) -> None:
        from news.integrations.pagebuilder import redirected_slug

        page = await _article(db, "old-name")
        page.slug = "new-name"
        db.add(page)
        await _record_redirect(db, page_id=page.id, old="old-name", new="new-name")
        await db.commit()

        assert await redirected_slug(db, "old-name", "en") == "new-name"

    async def test_a_slug_nobody_renamed_forwards_nowhere(self, db) -> None:
        from news.integrations.pagebuilder import redirected_slug

        await _article(db, "steady")

        assert await redirected_slug(db, "never-used", "en") is None
