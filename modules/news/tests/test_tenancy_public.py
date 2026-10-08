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
from tenant_app import as_tenant, create_published, multi_client

A, B = as_tenant("acme"), as_tenant("globex")
NEWS = "/news"
INERTIA = {"X-Inertia": "true"}

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]


@pytest.fixture
async def mt():
    async for client in multi_client(stub_user((ROLE_EDITOR,)), mount_public=True):
        yield client


@pytest.fixture
async def anon():
    async for client in multi_client(None, mount_public=True):
        yield client


async def test_public_article_per_tenant(mt: AsyncClient) -> None:
    await create_published(mt, A, "hello", "Hello A")
    assert (await mt.get(f"{NEWS}/hello", headers=A)).status_code == 200
    assert (await mt.get(f"{NEWS}/hello", headers=B)).status_code == 404
    unbound = await mt.get(f"{NEWS}/hello")
    assert unbound.status_code == 404
    assert unbound.json()["detail"] == "Article not found"


async def test_same_slug_serves_each_tenants_own_article(mt: AsyncClient) -> None:
    await create_published(mt, A, "about", "About Acme")
    await create_published(mt, B, "about", "About Globex")
    assert "About Acme" in (await mt.get(f"{NEWS}/about", headers=A)).text
    assert "About Globex" in (await mt.get(f"{NEWS}/about", headers=B)).text


async def test_feed_and_sitemap_per_tenant(mt: AsyncClient) -> None:
    await create_published(mt, A, "alpha-story", "Alpha story")
    await create_published(mt, B, "beta-story", "Beta story")
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


async def test_public_archives_list_only_the_bound_tenant(anon: AsyncClient) -> None:
    with tenant_context("acme"):
        async with anon.db_state.session_factory() as db:
            await make_article(db, slug="acme-sport", category="Sport", author="Jane Roe")
    for path in (f"{NEWS}/category/Sport", f"{NEWS}/author/jane-roe"):
        in_b = await anon.get(path, headers={**INERTIA, **B})
        assert in_b.status_code == 200, (path, in_b.text)
        assert in_b.json()["props"]["items"] == [], path
        in_a = await anon.get(path, headers={**INERTIA, **A})
        assert [i["slug"] for i in in_a.json()["props"]["items"]] == ["acme-sport"], path


def _vary(response) -> list[str]:
    """The distinct Vary fields: Starlette's ``SessionMiddleware`` appends
    ``Cookie`` without checking whether it is already listed."""
    fields = (v.strip() for v in response.headers.get("vary", "").split(","))
    return list(dict.fromkeys(f for f in fields if f))


async def test_multi_mode_public_responses_vary_on_cookie(mt: AsyncClient) -> None:
    """On the apex host the tenant can come from a member's session, so a
    shared cache keyed on Host + URL alone could hand one tenant's page to
    another tenant's reader."""
    await create_published(mt, A, "hello", "Hello A")
    for path in (
        f"{NEWS}/hello",
        f"{NEWS}/category/Sport",
        f"{NEWS}/feed.xml",
        f"{NEWS}/sitemap.xml",
    ):
        response = await mt.get(path, headers=A)
        assert response.status_code == 200, (path, response.text)
        assert response.headers["cache-control"].startswith("public"), path
        assert "Cookie" in _vary(response), (path, response.headers.get("vary"))
    article = await mt.get(f"{NEWS}/hello", headers=A)
    assert _vary(article) == ["X-Inertia", "Cookie"]
    cached = await mt.get(f"{NEWS}/hello", headers={**A, "If-None-Match": article.headers["etag"]})
    assert cached.status_code == 304
    assert _vary(cached) == ["X-Inertia", "Cookie"]


async def test_single_mode_vary_is_unchanged(anon_client: AsyncClient) -> None:
    """A single-tenant host picks no tenant per request: news adds nothing.

    The ``Cookie`` on the Inertia pages is Starlette's ``SessionMiddleware``,
    which varies on it whenever a render touched the session."""
    with tenant_context("default"):
        async with anon_client.db_state.session_factory() as db:
            await make_article(db, slug="hello", category="Sport")
    article = await anon_client.get(f"{NEWS}/hello")
    assert article.headers.get("vary") == "X-Inertia, Cookie"
    revalidate = {"If-None-Match": article.headers["etag"]}
    cached = await anon_client.get(f"{NEWS}/hello", headers=revalidate)
    assert (cached.status_code, cached.headers.get("vary")) == (304, "X-Inertia")
    for path, vary in (
        (f"{NEWS}/category/Sport", "Cookie"),
        (f"{NEWS}/feed.xml", None),
        (f"{NEWS}/sitemap.xml", None),
    ):
        response = await anon_client.get(path)
        assert response.status_code == 200, (path, response.text)
        assert response.headers.get("vary") == vary, path
