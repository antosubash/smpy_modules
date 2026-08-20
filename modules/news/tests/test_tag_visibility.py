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

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from news import tag_service
from news.models import NewsArticle
from pagebuilder.models import Page, PageStatus

pytestmark = pytest.mark.asyncio

TAGS = ["embargoed", "canopy"]


async def _seed(
    client: AsyncClient, *, status: PageStatus, trashed: bool = False
) -> int:
    """A tagged article on the client's own database. Returns its id."""
    async with client.db_state.session_factory() as session:  # type: ignore[attr-defined]
        page = Page(slug="subject", title="Subject", status=status, draft_data={})
        session.add(page)
        await session.commit()
        await session.refresh(page)

        article = NewsArticle(page_id=page.id, category="Research")
        session.add(article)
        await session.commit()
        await session.refresh(article)

        await tag_service.set_for_article(session, article.id or 0, TAGS)
        if trashed:
            page.deleted_at = datetime.now(UTC)
            session.add(page)
        await session.commit()
        return article.id or 0


async def test_a_drafts_tags_are_not_public(anon_client: AsyncClient) -> None:
    """The leak this file exists for."""
    article_id = await _seed(anon_client, status=PageStatus.DRAFT)

    response = await anon_client.get(f"/api/news/articles/{article_id}/tags")

    assert response.status_code == 404, response.text
    assert "embargoed" not in response.text


async def test_a_trashed_articles_tags_are_not_public(anon_client: AsyncClient) -> None:
    """A trashed page is invisible everywhere else; its tags are no exception."""
    article_id = await _seed(anon_client, status=PageStatus.PUBLISHED, trashed=True)

    response = await anon_client.get(f"/api/news/articles/{article_id}/tags")

    assert response.status_code == 404, response.text
    assert "embargoed" not in response.text


async def test_a_published_articles_tags_stay_public(anon_client: AsyncClient) -> None:
    """The contract that must not regress — this is an anonymously-readable API."""
    article_id = await _seed(anon_client, status=PageStatus.PUBLISHED)

    response = await anon_client.get(f"/api/news/articles/{article_id}/tags")

    assert response.status_code == 200, response.text
    assert sorted(response.json()) == sorted(TAGS)


async def test_an_editor_still_reads_a_drafts_tags(editor_client: AsyncClient) -> None:
    """The article editor loads exactly this while the article is still a draft."""
    article_id = await _seed(editor_client, status=PageStatus.DRAFT)

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
