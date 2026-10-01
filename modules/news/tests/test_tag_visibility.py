"""Tags obey the same draft-visibility rule as everything else they hang off.

``GET /articles/{id}/tags`` sits under ``PUBLIC_READ_PREFIXES``, which the
registry matches with ``str.startswith`` — so it is anonymously readable
exactly like the listing is. The listing gates on :func:`may_see_drafts`; if
this route does not, an anonymous visitor who guesses an id reads the tags of
an article that has not been published yet.

Seeding goes through ``client.db_state`` rather than the ``db`` fixture: each
client fixture builds its own in-memory database, so a row written through
``db`` is invisible to the app under test.
"""

from __future__ import annotations

import pytest
from factories import make_article
from httpx import AsyncClient
from news import tag_service
from news.content import ArticlesService
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio

TAGS = ["embargoed", "canopy"]


async def _seed(
    client: AsyncClient, *, status: ArticleStatus, trashed: bool = False
) -> int:
    """A tagged article on the client's own database. Returns its id."""
    async with client.db_state.session_factory() as session:  # type: ignore[attr-defined]
        article = await make_article(
            session, slug="subject", title="Subject", status=status,
            category="Research",
        )
        await tag_service.set_for_article(session, article.id or 0, TAGS)
        if trashed:
            # The article's own column now. It used to be the joined page's,
            # which is why "trashed" once meant something happening in another
            # module's table.
            await ArticlesService(session).trash(article.id or 0)
        await session.commit()
        return article.id or 0


async def test_a_drafts_tags_are_not_public(anon_client: AsyncClient) -> None:
    """The leak this file exists for."""
    article_id = await _seed(anon_client, status=ArticleStatus.DRAFT)

    response = await anon_client.get(f"/api/news/articles/{article_id}/tags")

    assert response.status_code == 404, response.text
    assert "embargoed" not in response.text


async def test_a_trashed_articles_tags_are_not_public(anon_client: AsyncClient) -> None:
    """A trashed article is invisible everywhere else; its tags are no exception."""
    article_id = await _seed(anon_client, status=ArticleStatus.PUBLISHED, trashed=True)

    response = await anon_client.get(f"/api/news/articles/{article_id}/tags")

    assert response.status_code == 404, response.text
    assert "embargoed" not in response.text


async def test_a_published_articles_tags_stay_public(anon_client: AsyncClient) -> None:
    """The contract that must not regress — this is an anonymously-readable API."""
    article_id = await _seed(anon_client, status=ArticleStatus.PUBLISHED)

    response = await anon_client.get(f"/api/news/articles/{article_id}/tags")

    assert response.status_code == 200, response.text
    assert sorted(response.json()) == sorted(TAGS)


async def test_an_editor_still_reads_a_drafts_tags(editor_client: AsyncClient) -> None:
    """The article editor loads exactly this while the article is still a draft."""
    article_id = await _seed(editor_client, status=ArticleStatus.DRAFT)

    response = await editor_client.get(f"/api/news/articles/{article_id}/tags")

    assert response.status_code == 200, response.text
    assert sorted(response.json()) == sorted(TAGS)


async def test_tags_for_a_missing_article_are_404_not_empty(
    anon_client: AsyncClient,
) -> None:
    """An empty list claims "this article has no tags", which is a different
    thing from "there is no such article"."""
    response = await anon_client.get("/api/news/articles/999999/tags")

    assert response.status_code == 404, response.text


async def test_the_editors_single_read_carries_the_tags(editor_client: AsyncClient) -> None:
    """The editor loads an article by id, and saves back whatever tags it read.

    A single read without them would hand the editor an untagged article, and
    its next Save would write that back over the real ones.
    """
    article_id = await _seed(editor_client, status=ArticleStatus.DRAFT)

    detail = await editor_client.get(f"/api/news/articles/{article_id}/detail")
    assert detail.status_code == 200
    assert sorted(detail.json()["tags"]) == sorted(TAGS)

    submitted = await editor_client.post(f"/api/news/articles/{article_id}/submit")
    assert submitted.status_code == 200
    assert sorted(submitted.json()["tags"]) == sorted(TAGS)
