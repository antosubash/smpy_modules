"""The admin list says a draft is waiting to go live (#449).

``scheduled_at`` is editorial, like ``has_unpublished_changes``: a reader is
never told what is queued, and only a draft can be waiting.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from news.core.constants import ROUTE_PREFIX_API
from news.models import ArticleStatus

from tests.support.factories import make_article

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"


async def seed(client, slug: str, *, publish_at=None, status=ArticleStatus.DRAFT) -> None:
    async with client.db_state.session_factory() as db:
        article = await make_article(db, slug=slug, title=slug, status=status)
        article.publish_at = publish_at
        db.add(article)
        await db.commit()


async def listed(client) -> dict[str, dict]:
    response = await client.get(ARTICLES, params={"limit": 50})
    assert response.status_code == 200
    return {item["slug"]: item for item in response.json()["items"]}


class TestScheduledAt:
    async def test_a_scheduled_draft_carries_its_go_live_instant(self, editor_client) -> None:
        due = datetime.now(UTC) + timedelta(days=2)
        await seed(editor_client, "queued", publish_at=due)
        await seed(editor_client, "plain")

        items = await listed(editor_client)

        assert items["queued"]["scheduled_at"] is not None
        got = datetime.fromisoformat(items["queued"]["scheduled_at"].replace("Z", "+00:00"))
        assert abs((got - due).total_seconds()) < 1
        assert items["plain"]["scheduled_at"] is None

    async def test_a_published_article_carries_none(self, editor_client) -> None:
        due = datetime.now(UTC) + timedelta(days=2)
        await seed(editor_client, "live", publish_at=due, status=ArticleStatus.PUBLISHED)

        assert (await listed(editor_client))["live"]["scheduled_at"] is None

    async def test_a_reader_is_never_told(self, anon_client) -> None:
        due = datetime.now(UTC) + timedelta(days=2)
        await seed(anon_client, "live", publish_at=due, status=ArticleStatus.PUBLISHED)
        await seed(anon_client, "queued", publish_at=due)

        response = await anon_client.get(ARTICLES, params={"limit": 50})

        assert response.status_code == 200
        items = response.json()["items"]
        assert [item["slug"] for item in items] == ["live"]
        assert items[0]["scheduled_at"] is None
