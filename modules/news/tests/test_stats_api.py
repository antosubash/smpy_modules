"""``GET /api/news/stats`` — the number the NewsStats block shows.

The count is public and cacheable, so the cases that matter are the ones where a
row must *not* be counted: a draft, a trashed article, an embargo that has
expired, another tenant's. Each has a test, because a count that leaks any of
them tells an anonymous reader something the listing would never have shown.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import ROLE_EDITOR
from factories import make_article
from httpx import AsyncClient
from news.constants import ROUTE_PREFIX_API
from news.models import ArticleStatus
from simple_module_db import tenant_context
from stub_auth import stub_user
from tenant_app import as_tenant, multi_client

pytestmark = pytest.mark.asyncio

STATS = f"{ROUTE_PREFIX_API}/stats"
A, B = as_tenant("acme"), as_tenant("globex")


async def _seed(client: AsyncClient, **kwargs):
    async with client.db_state.session_factory() as db:
        return await make_article(db, **kwargs)


async def _alter(client: AsyncClient, article, **columns) -> None:
    async with client.db_state.session_factory() as db:
        row = await db.get(type(article), article.id)
        for name, value in columns.items():
            setattr(row, name, value)
        await db.commit()


async def test_counts_only_published_live_articles(anon_client: AsyncClient) -> None:
    now = datetime.now(UTC)
    await _seed(anon_client, slug="p1")
    await _seed(anon_client, slug="p2")
    await _seed(anon_client, slug="draft", status=ArticleStatus.DRAFT)
    trashed = await _seed(anon_client, slug="trashed")
    await _alter(anon_client, trashed, deleted_at=now)
    expired = await _seed(anon_client, slug="expired")
    await _alter(anon_client, expired, unpublish_at=now - timedelta(hours=1))
    embargoed = await _seed(anon_client, slug="embargoed")
    await _alter(anon_client, embargoed, unpublish_at=now + timedelta(hours=1))

    response = await anon_client.get(STATS, params={"metric": "published"})

    assert response.status_code == 200, response.text
    assert response.json() == {"value": 3}


async def test_category_and_locale_narrow(anon_client: AsyncClient) -> None:
    await _seed(anon_client, slug="en-a", locale="en", category="a")
    await _seed(anon_client, slug="en-b", locale="en", category="b")
    await _seed(anon_client, slug="de-a", locale="de", category="a")

    async def count(**params: str) -> int:
        response = await anon_client.get(STATS, params={"metric": "published", **params})
        assert response.status_code == 200, response.text
        return response.json()["value"]

    assert await count() == 3
    assert await count(category="a") == 2
    assert await count(locale="de") == 1
    assert await count(category="a", locale="de") == 1


async def test_anonymous_cache_headers(anon_client: AsyncClient) -> None:
    response = await anon_client.get(STATS, params={"metric": "published"})

    assert response.headers["Cache-Control"] == "public, max-age=60"
    assert "Cookie" in response.headers["Vary"]


async def test_head_answers(anon_client: AsyncClient) -> None:
    # Through the real routing and the stub auth middleware, with no dependency
    # overridden: HEAD is a different method to the public-route registry, so a
    # prefix registered for GET alone would still ask a prober for a session.
    response = await anon_client.head(STATS, params={"metric": "published"})

    assert response.status_code == 200
    assert response.content == b""


async def test_unknown_metric_is_422(anon_client: AsyncClient) -> None:
    response = await anon_client.get(STATS, params={"metric": "drafts"})

    assert response.status_code == 422


@pytest.mark.unbound_tenant
async def test_other_tenant_not_counted() -> None:
    async for client in multi_client(stub_user((ROLE_EDITOR,)), mount_public=True):
        with tenant_context("globex"):
            await _seed(client, slug="globex-only")

        in_a = await client.get(STATS, params={"metric": "published"}, headers=A)
        in_b = await client.get(STATS, params={"metric": "published"}, headers=B)

        assert in_a.json() == {"value": 0}
        assert in_b.json() == {"value": 1}
