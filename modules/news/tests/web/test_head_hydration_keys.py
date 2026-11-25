"""Hydration adopts the server's head instead of doubling it (#451).

The server's tags and the client's ``<Head>`` must share Inertia keys.
Inertia's head manager only de-duplicates elements carrying ``data-inertia``;
the React side sets the same key through ``head-key``. Without the marker the
server's copy is invisible to it and hydration adds a second canonical, a second
of every ``og:`` tag and a second JSON-LD.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from news.core import settings as news_settings
from news.core.settings import NewsSettings

from tests.support.factories import make_article

pytestmark = pytest.mark.asyncio

NEWS = "/news"
ARTICLE_HEAD = (
    Path(__file__).resolve().parents[2] / "news" / "ui" / "components" / "ArticleHead.tsx"
)


class TestKeys:
    async def test_every_server_key_is_one_the_client_renders(
        self, anon_client
    ) -> None:
        async with anon_client.db_state.session_factory() as db:
            article = await make_article(
                db,
                slug="keyed",
                title="Keyed",
                meta_description="d",
                og_image="https://example.org/c.png",
                category="News",
                author="Ada",
                published_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
            article.json_ld = {"@type": "NewsArticle"}
            article.index_in_search = False
            db.add(article)
            await db.commit()
        news_settings.use(NewsSettings(site_name="S", twitter_handle="@s"))
        try:
            body = (await anon_client.get(f"{NEWS}/keyed")).text
        finally:
            news_settings.reset()

        head = body.split("</head>", 1)[0]
        server = re.findall(r'data-inertia="([^"]+)"', head)
        client = set(
            re.findall(r'head-key="([^"]+)"', ARTICLE_HEAD.read_text(encoding="utf-8"))
        )
        assert len(server) == len(set(server)), "a key appears twice in the head"
        assert set(server) == client

    async def test_a_tag_only_the_server_writes_is_not_managed(
        self, anon_client
    ) -> None:
        # The client never renders hreflang or the feed link, so a key on one
        # would make hydration delete it.
        body = (await anon_client.get(f"{NEWS}/")).text
        head = body.split("</head>", 1)[0]
        assert 'rel="alternate"' in head
        assert 'rel="canonical"' in head
        assert "data-inertia" not in head.split('rel="alternate"', 1)[1].split(">", 1)[0]
