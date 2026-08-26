"""Metadata that exists before JavaScript runs.

`PublicArticle.tsx` composes a careful head through Inertia's ``<Head>`` — og
tags, a description, a canonical link, JSON-LD — and every one of them appeared
only after the bundle executed. Google runs JavaScript; Slack, X, LinkedIn,
Facebook and feed tooling do not, so an article link previewed as the
application's name with no description and no image.

Every assertion here reads the *raw* HTML, without an ``X-Inertia`` header and
without executing anything. That is exactly what an unfurler sees.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news import settings as news_settings
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
