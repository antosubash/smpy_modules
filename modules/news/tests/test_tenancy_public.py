"""The anonymous surface's isolation between two live tenants.

Ported from pagebuilder's: the viewer, the feed, the sitemap — and the API
reads the feed block makes anonymously (``PUBLIC_READ_PREFIXES``).
"""

from __future__ import annotations

import pytest
from conftest import ROLE_EDITOR
from factories import make_article
from httpx import AsyncClient
from news.constants import PUBLIC_READ_PREFIXES
from simple_module_db import tenant_context
from stub_auth import stub_user
from tenant_app import as_tenant, create_article, multi_client, publish

A, B = as_tenant("acme"), as_tenant("globex")
NEWS = "/news"

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]


@pytest.fixture
async def mt():
    async for client in multi_client(stub_user((ROLE_EDITOR,)), mount_public=True):
        yield client


@pytest.fixture
async def anon():
    async for client in multi_client(None, mount_public=True):
        yield client


async def _live(client: AsyncClient, headers, slug: str, title: str) -> dict:
    article = await create_article(client, headers, slug, title)
    await publish(client, headers, article["id"])
    return article


async def test_public_article_per_tenant(mt: AsyncClient) -> None:
    await _live(mt, A, "hello", "Hello A")
    assert (await mt.get(f"{NEWS}/hello", headers=A)).status_code == 200
    assert (await mt.get(f"{NEWS}/hello", headers=B)).status_code == 404
    unbound = await mt.get(f"{NEWS}/hello")
    assert unbound.status_code == 404
    assert unbound.json()["detail"] == "Article not found"


async def test_same_slug_serves_each_tenants_own_article(mt: AsyncClient) -> None:
    await _live(mt, A, "about", "About Acme")
    await _live(mt, B, "about", "About Globex")
    assert "About Acme" in (await mt.get(f"{NEWS}/about", headers=A)).text
    assert "About Globex" in (await mt.get(f"{NEWS}/about", headers=B)).text


async def test_feed_and_sitemap_per_tenant(mt: AsyncClient) -> None:
    await _live(mt, A, "alpha-story", "Alpha story")
    await _live(mt, B, "beta-story", "Beta story")
    for path in (f"{NEWS}/feed.xml", f"{NEWS}/sitemap.xml"):
        a = await mt.get(path, headers=A)
        b = await mt.get(path, headers=B)
        assert a.status_code == b.status_code == 200, (path, a.text, b.text)
        assert "alpha-story" in a.text and "beta-story" not in a.text
        assert "beta-story" in b.text and "alpha-story" not in b.text
        assert (await mt.get(path)).status_code == 404


async def test_anonymous_api_read_scoped(anon: AsyncClient) -> None:
    with tenant_context("acme"):
        async with anon.db_state.session_factory() as db:
            await make_article(db, slug="acme-only", title="Acme only", category="Sport")
    for prefix in PUBLIC_READ_PREFIXES:
        in_b = await anon.get(prefix, headers=B)
        assert in_b.status_code == 200, in_b.text
        assert "acme-only" not in in_b.text and "Sport" not in in_b.text
        in_a = await anon.get(prefix, headers=A)
        assert in_a.status_code == 200, in_a.text
    listed = (await anon.get(PUBLIC_READ_PREFIXES[0], headers=A)).json()["items"]
    assert [a["slug"] for a in listed] == ["acme-only"]
