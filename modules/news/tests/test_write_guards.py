"""Guards on the write API that each closed a specific hole.

Each was found by review rather than by a failing screen, which is why they are
pinned here: none of them is visible in the normal flow, and each fails in a way
that names the wrong problem or quietly widens what a role can do.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from factories import make_article
from news.constants import ROUTE_PREFIX_API
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"


async def _article(client, slug: str, status: ArticleStatus) -> int:
    async with client.db_state.session_factory() as db:
        article = await make_article(db, slug=slug, title="Subject", status=status)
        return article.id or 0


async def test_an_author_cannot_unpublish_by_submitting(author_client) -> None:
    """Submit needs only news.edit and moves the article to review. From PUBLISHED
    that would take it off the site — which is news.publish's to do."""
    article_id = await _article(author_client, "live", ArticleStatus.PUBLISHED)

    response = await author_client.post(f"{ARTICLES}/{article_id}/submit")

    assert response.status_code == 409, response.text
    listed = (await author_client.get(f"{ARTICLES}?status=published")).json()
    assert [item["id"] for item in listed["items"]] == [article_id]


@pytest.mark.parametrize("field", ["title", "slug", "index_in_search"])
async def test_null_for_a_required_field_is_a_422(editor_client, field: str) -> None:
    """Otherwise the NOT NULL failure surfaces as "Slug already in use"."""
    slug = f"null-{field}".replace("_", "-")
    article_id = await _article(editor_client, slug, ArticleStatus.DRAFT)

    response = await editor_client.put(f"{ARTICLES}/{article_id}", json={field: None})

    assert response.status_code == 422, response.text


async def test_a_schedule_is_stored_in_utc(editor_client) -> None:
    """Sent with an offset, read back as the same instant in UTC. SQLite drops
    the offset without converting, so an unconverted +02:00 time would fire two
    hours late."""
    article_id = await _article(editor_client, "zoned", ArticleStatus.DRAFT)
    instant = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
    sent = instant.astimezone(timezone(timedelta(hours=2)))

    response = await editor_client.post(
        f"{ARTICLES}/{article_id}/schedule", json={"publish_at": sent.isoformat()}
    )
    assert response.status_code == 200, response.text

    detail = (await editor_client.get(f"{ARTICLES}/{article_id}/detail")).json()
    assert datetime.fromisoformat(detail["publish_at"]) == instant
