"""The recoverable admin deletion path and its public effects (#445)."""

from datetime import UTC, datetime, timedelta

import pytest
from news.content.articles import ArticlesService
from news.core.constants import ROUTE_PREFIX_API
from news.models import ArticleStatus, NewsArticle

from tests.support.factories import make_article

pytestmark = pytest.mark.asyncio
ARTICLES = f"{ROUTE_PREFIX_API}/articles"


async def test_published_trash_hides_both_addresses_and_restore_keeps_content(editor_public_client):
    client = editor_public_client
    created = (await client.post(ARTICLES, json={"title": "Original", "slug": "old"})).json()
    url = f"{ARTICLES}/{created['id']}"
    assert (await client.post(f"{url}/publish")).status_code == 200
    assert (await client.put(url, json={"slug": "new"})).status_code == 200
    assert (await client.get("/news/new")).status_code == 200
    assert (await client.get("/news/old")).status_code == 301
    assert (await client.post(f"{url}/trash")).status_code == 204
    assert (await client.get("/news/new")).status_code == 404
    assert (await client.get("/news/old")).status_code == 404
    assert (await client.get(ARTICLES)).json()["total"] == 0
    trash = (await client.get(ARTICLES, params={"trashed": True})).json()
    assert [row["id"] for row in trash["items"]] == [created["id"]]
    collision = await client.post(ARTICLES, json={"title": "Other", "slug": "new"})
    assert collision.status_code == 409
    restored = await client.post(f"{url}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "published"
    assert (await client.get("/news/new")).status_code == 200
    assert (await client.get("/news/old")).status_code == 301


@pytest.mark.parametrize("status", [ArticleStatus.DRAFT, ArticleStatus.PUBLISHED])
async def test_restore_clears_elapsed_schedules_and_keeps_future_ones(db, status):
    article = await make_article(db, slug="scheduled", status=status)
    now = datetime.now(UTC)
    article.publish_at = now - timedelta(days=1)
    article.unpublish_at = now + timedelta(days=1)
    db.add(article)
    await db.commit()
    service = ArticlesService(db)
    await service.trash(article.id)
    await db.commit()
    assert await service.process_due(now) == []
    await service.restore(article.id)
    assert article.status == status
    assert article.publish_at is None
    assert article.unpublish_at.replace(tzinfo=UTC) > now


async def test_author_can_trash_and_restore_but_cannot_purge(author_client):
    client = author_client
    article = (await client.post(ARTICLES, json={"title": "Recoverable"})).json()
    url = f"{ARTICLES}/{article['id']}"
    assert (await client.post(f"{url}/trash")).status_code == 204
    assert (await client.delete(f"{url}/purge")).status_code == 403
    assert (await client.post(f"{url}/restore")).status_code == 200


async def test_purge_removes_a_trashed_row_and_frees_its_slug(editor_client):
    client = editor_client
    article = (await client.post(ARTICLES, json={"title": "Subject", "slug": "subject"})).json()
    url = f"{ARTICLES}/{article['id']}"
    assert (await client.post(f"{url}/trash")).status_code == 204
    assert (await client.delete(f"{url}/purge")).status_code == 204
    assert (await client.post(f"{url}/restore")).status_code == 404
    async with client.db_state.session_factory() as db:
        assert await db.get(NewsArticle, article["id"]) is None
    assert (
        await client.post(ARTICLES, json={"title": "Replacement", "slug": "subject"})
    ).status_code == 201
