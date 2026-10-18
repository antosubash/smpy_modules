"""HEAD on the public archive answers exactly like GET, minus the body (#76).

Link checkers, uptime probes and crawlers send HEAD before they GET. The
viewer routes registered GET only, so Starlette answered 405 to every one of
them; the auth exemption already listed HEAD, so the gap was in the routes.

Everything is compared against the GET for the same URL rather than against
constants, so a header added to one verb and not the other fails here.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news import locales
from news.content import ArticlesService
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio

NEWS = "/news"
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


async def _seed(client, slug: str, **kwargs):
    async with client.db_state.session_factory() as db:
        return await make_article(db, slug=slug, title=slug, **kwargs)


async def _same_as_get(client, url: str, status: int, **kwargs):
    get = await client.get(url, **kwargs)
    head = await client.head(url, **kwargs)
    assert head.status_code == get.status_code == status
    assert head.content == b""
    assert head.headers == get.headers
    return get, head


class TestArticle:
    @pytest.mark.parametrize("headers", [{}, INERTIA])
    async def test_published_article(self, anon_client, headers) -> None:
        await _seed(anon_client, "hello")

        get, head = await _same_as_get(anon_client, f"{NEWS}/hello", 200, headers=headers)

        assert head.headers["etag"] == get.headers["etag"]
        assert "max-age" in head.headers["cache-control"]
        assert head.headers["cache-control"] == get.headers["cache-control"]

    async def test_conditional_request_is_304(self, anon_client) -> None:
        await _seed(anon_client, "hello")
        etag = (await anon_client.get(f"{NEWS}/hello")).headers["etag"]

        await _same_as_get(anon_client, f"{NEWS}/hello", 304, headers={"If-None-Match": etag})

    async def test_missing_and_draft_are_404(self, anon_client) -> None:
        await _seed(anon_client, "wip", status=ArticleStatus.DRAFT, publish_body=False)

        await _same_as_get(anon_client, f"{NEWS}/never-existed", 404)
        await _same_as_get(anon_client, f"{NEWS}/wip", 404)

    async def test_renamed_article_is_301(self, anon_client) -> None:
        article = await _seed(anon_client, "old-name")
        async with anon_client.db_state.session_factory() as db:
            await ArticlesService(db).update(article.id, {"slug": "new-name"})
            await db.commit()

        _, head = await _same_as_get(anon_client, f"{NEWS}/old-name", 301, follow_redirects=False)

        assert head.headers["location"] == "/news/new-name"

    async def test_other_languages_slug_is_not_served(self, bilingual_public_client) -> None:
        # A HEAD for /de/news/x must not answer for the English article.
        await _seed(bilingual_public_client, "english-only", locale="en")

        await _same_as_get(bilingual_public_client, f"/de{NEWS}/english-only", 404)

    async def test_default_locale_alias_is_301(self, bilingual_public_client) -> None:
        await _seed(bilingual_public_client, "hello")

        _, head = await _same_as_get(
            bilingual_public_client,
            f"/{locales.default()}{NEWS}/hello",
            301,
            follow_redirects=False,
        )

        assert head.headers["location"] == "/news/hello"


class TestArchivePages:
    @pytest.mark.parametrize("path", ["/", "/feed.xml", "/sitemap.xml"])
    async def test_populated_surfaces_are_200(self, anon_client, path: str) -> None:
        await _seed(anon_client, "hello")

        await _same_as_get(anon_client, f"{NEWS}{path}", 200)

    @pytest.mark.parametrize("path", ["/category/none", "/tag/none", "/author/none"])
    async def test_taxonomy_pages_match_get(self, anon_client, path: str) -> None:
        await _seed(anon_client, "hello")
        url = f"{NEWS}{path}"

        get = await anon_client.get(url)
        head = await anon_client.head(url)

        assert head.status_code == get.status_code
        assert head.status_code != 405
        assert head.content == b""
        assert head.headers == get.headers
