"""Metadata that exists before JavaScript runs.

`PublicArticle.tsx` composes a careful head through Inertia's ``<Head>`` — og
tags, a description, a canonical link, JSON-LD — and every one of them appeared
only after the bundle executed. Google runs JavaScript; Slack, X, LinkedIn,
Facebook and feed tooling do not, so an article link previewed as the
application's name with no description and no image.

Every assertion here reads the *raw* HTML, without an ``X-Inertia`` header and
without executing anything. That is exactly what an unfurler sees.

``hreflang`` is here for the same reason and not in ``test_locale_addressing``
with the rest of the language rules: a crawler deciding which language to index
for a query does it without running the script, so a language switch that only
exists after the bundle executes is a language switch that does not exist.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news import settings as news_settings
from news.models import ArticleStatus
from news.settings import NewsSettings

pytestmark = pytest.mark.asyncio

NEWS = "/news"


class TestArticleHead:
    async def test_the_title_is_the_headline_not_the_app_name(
        self, anon_client
    ) -> None:
        async with anon_client.db_state.session_factory() as db:
            await make_article(db, slug="titled", title="Sensor rollout completes")

        body = (await anon_client.get(f"{NEWS}/titled")).text

        assert "<title>Sensor rollout completes</title>" in body
        # The shell's own title is removed rather than left beside ours: two
        # titles let the consumer pick, which in practice means the wrong one.
        assert body.count("<title>") == 1

    async def test_it_carries_the_open_graph_tags_a_preview_needs(
        self, anon_client
    ) -> None:
        async with anon_client.db_state.session_factory() as db:
            await make_article(
                db,
                slug="unfurled",
                title="Unfurled",
                meta_description="Two months ahead of schedule.",
                og_image="https://example.org/cover.png",
            )

        body = (await anon_client.get(f"{NEWS}/unfurled")).text

        assert '<meta property="og:title" content="Unfurled">' in body
        assert '<meta property="og:type" content="article">' in body
        assert 'content="Two months ahead of schedule."' in body
        assert 'content="https://example.org/cover.png"' in body
        assert '<meta name="twitter:card" content="summary_large_image">' in body

    async def test_a_summary_card_without_an_image(self, anon_client) -> None:
        async with anon_client.db_state.session_factory() as db:
            await make_article(db, slug="plain", title="Plain")

        body = (await anon_client.get(f"{NEWS}/plain")).text

        assert '<meta name="twitter:card" content="summary">' in body

    async def test_it_carries_the_canonical_link(self, anon_client) -> None:
        async with anon_client.db_state.session_factory() as db:
            await make_article(db, slug="canonical", title="Canonical")

        body = (await anon_client.get(f"{NEWS}/canonical")).text

        assert 'rel="canonical"' in body
        assert f"{NEWS}/canonical" in body

    async def test_noindex_reaches_a_crawler_that_runs_no_script(
        self, anon_client
    ) -> None:
        # The one tag where client-side rendering was not merely unhelpful but
        # actively wrong: a crawler that does not execute the bundle would have
        # indexed an article explicitly marked not to be.
        async with anon_client.db_state.session_factory() as db:
            article = await make_article(db, slug="private", title="Private")
            article.index_in_search = False
            db.add(article)
            await db.commit()

        body = (await anon_client.get(f"{NEWS}/private")).text

        assert '<meta name="robots" content="noindex,nofollow">' in body

    async def test_a_headline_with_a_quote_does_not_break_the_attribute(
        self, anon_client
    ) -> None:
        async with anon_client.db_state.session_factory() as db:
            await make_article(db, slug="quoted", title='He said "no"')

        body = (await anon_client.get(f"{NEWS}/quoted")).text

        assert 'content="He said &quot;no&quot;"' in body

    async def test_json_ld_cannot_break_out_of_its_script(self, anon_client) -> None:
        async with anon_client.db_state.session_factory() as db:
            article = await make_article(db, slug="ld", title="LD")
            article.json_ld = {"name": "</script><script>alert(1)</script>"}
            db.add(article)
            await db.commit()

        body = (await anon_client.get(f"{NEWS}/ld")).text

        assert "<\\/script>" in body
        assert "<script>alert(1)</script>" not in body

    async def test_the_site_name_and_handle_appear_when_configured(
        self, anon_client
    ) -> None:
        news_settings.use(
            NewsSettings(site_name="The Archive", twitter_handle="@archive")
        )
        try:
            async with anon_client.db_state.session_factory() as db:
                await make_article(db, slug="branded", title="Branded")

            body = (await anon_client.get(f"{NEWS}/branded")).text

            assert 'content="The Archive"' in body
            assert 'content="@archive"' in body
        finally:
            news_settings.reset()


class TestListingHead:
    async def test_the_archive_advertises_its_feed(self, anon_client) -> None:
        # Feed autodiscovery. Without this the feed exists but is findable only
        # by guessing its address.
        body = (await anon_client.get(f"{NEWS}/")).text

        assert 'rel="alternate"' in body
        assert 'type="application/rss+xml"' in body
        assert f"{NEWS}/feed.xml" in body

    async def test_an_archive_page_is_a_website_not_an_article(
        self, anon_client
    ) -> None:
        body = (await anon_client.get(f"{NEWS}/")).text
        assert '<meta property="og:type" content="website">' in body


class TestTheViewerAdvertisesItsTranslations:
    """``hreflang``, server-rendered.

    A crawler deciding which language to index for a query does it without
    running the script, so a switch that only exists after the bundle executes
    is a switch that does not exist.
    """

    async def _pair(self, client) -> None:
        async with client.db_state.session_factory() as db:
            english = await make_article(
                db, slug="budget", title="Budget", locale="en"
            )
            await make_article(
                db,
                slug="haushalt",
                title="Haushalt",
                locale="de",
                translation_group=english.translation_group,
            )

    async def test_each_language_is_linked_from_the_other(
        self, bilingual_public_client
    ) -> None:
        await self._pair(bilingual_public_client)

        body = (await bilingual_public_client.get("/news/budget")).text

        assert 'hreflang="en"' in body
        assert 'hreflang="de"' in body
        assert "/de/news/haushalt" in body

    async def test_x_default_names_the_sites_own_language(
        self, bilingual_public_client
    ) -> None:
        """The version to serve someone whose language nobody matched. The
        site's default is the only defensible answer."""
        await self._pair(bilingual_public_client)

        body = (await bilingual_public_client.get("/de/news/haushalt")).text

        assert 'hreflang="x-default"' in body

    async def test_an_untranslated_article_advertises_nothing(
        self, bilingual_public_client
    ) -> None:
        """A lone ``hreflang`` pointing at the document itself says nothing and
        is noise in the head of every page."""
        async with bilingual_public_client.db_state.session_factory() as db:
            await make_article(db, slug="alone", locale="en")

        body = (await bilingual_public_client.get("/news/alone")).text

        assert "hreflang" not in body

    async def test_a_draft_translation_is_not_advertised(
        self, bilingual_public_client
    ) -> None:
        """Pointing a crawler at a 404 and offering a reader a language switch
        that dead-ends."""
        async with bilingual_public_client.db_state.session_factory() as db:
            english = await make_article(db, slug="budget", locale="en")
            await make_article(
                db,
                slug="haushalt",
                locale="de",
                status=ArticleStatus.DRAFT,
                translation_group=english.translation_group,
            )

        body = (await bilingual_public_client.get("/news/budget")).text

        assert "haushalt" not in body

    async def test_the_response_says_which_language_it_is(
        self, bilingual_public_client
    ) -> None:
        """For caches, and for anything reading the response without parsing
        the body."""
        await self._pair(bilingual_public_client)

        response = await bilingual_public_client.get("/de/news/haushalt")

        assert response.headers["Content-Language"] == "de"


