"""The anonymous viewer's isolation, and the single-tenant stamp (#38)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from tenant_app import as_tenant, create_page, multi_client

API = "/api/pagebuilder/pages"
A, B = as_tenant("acme"), as_tenant("globex")
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def mt(tmp_path):
    async for client in multi_client(tmp_path):
        yield client


async def _publish(client: AsyncClient, headers, slug: str, title: str) -> dict:
    page = await create_page(client, headers, slug, title)
    done = await client.post(f"{API}/{page['id']}/publish", json={}, headers=headers)
    assert done.status_code == 200, done.text
    return page


async def _title(client: AsyncClient, path: str, headers) -> str:
    response = await client.get(path, headers={**INERTIA, **headers})
    assert response.status_code == 200, response.text
    return response.json()["props"]["title"]


@pytest.mark.unbound_tenant
async def test_same_slug_serves_each_tenants_own_page(mt: AsyncClient) -> None:
    await _publish(mt, A, "about", "About Acme")
    await _publish(mt, B, "about", "About Globex")
    assert await _title(mt, "/p/about", A) == "About Acme"
    assert await _title(mt, "/p/about", B) == "About Globex"


@pytest.mark.unbound_tenant
async def test_a_slug_in_another_tenant_is_404(mt: AsyncClient) -> None:
    await _publish(mt, B, "only-b", "Only B")
    assert (await mt.get("/p/only-b", headers=A)).status_code == 404
    assert (await mt.get("/p/only-b", headers=B)).status_code == 200


@pytest.mark.unbound_tenant
async def test_rename_redirect_resolves_only_for_its_tenant(mt: AsyncClient) -> None:
    page = await _publish(mt, A, "old", "Moved")
    await mt.put(f"{API}/{page['id']}", json={"slug": "new"}, headers=A)
    await mt.post(f"{API}/{page['id']}/publish", json={}, headers=A)
    moved = await mt.get("/p/old", headers=A)
    assert moved.status_code == 301
    assert moved.headers["location"] == "/p/new"
    assert (await mt.get("/p/old", headers=B)).status_code == 404


@pytest.mark.unbound_tenant
@pytest.mark.parametrize("path", ["/p/x", "/sitemap.xml"])
async def test_no_tenant_is_404_not_500(mt: AsyncClient, path: str) -> None:
    await _publish(mt, A, "x", "X")
    assert (await mt.get(path)).status_code == 404


@pytest.mark.unbound_tenant
async def test_sitemap_lists_only_the_bound_tenant(mt: AsyncClient) -> None:
    await _publish(mt, A, "alpha", "Alpha")
    await _publish(mt, B, "beta", "Beta")
    a = await mt.get("/sitemap.xml", headers=A)
    b = await mt.get("/sitemap.xml", headers=B)
    assert a.status_code == b.status_code == 200
    assert "/p/alpha" in a.text and "/p/beta" not in a.text
    assert "/p/beta" in b.text and "/p/alpha" not in b.text


def _vary(response) -> list[str]:
    """The distinct Vary fields: Starlette's ``SessionMiddleware`` appends
    ``Cookie`` without checking whether it is already listed."""
    fields = (v.strip() for v in response.headers.get("vary", "").split(","))
    return list(dict.fromkeys(f for f in fields if f))


@pytest.mark.unbound_tenant
async def test_multi_mode_public_responses_vary_on_cookie(mt: AsyncClient) -> None:
    """The apex host can take the tenant from a member's session, so a shared
    cache keyed on Host + URL alone could serve one tenant's page to another."""
    await _publish(mt, A, "about", "About Acme")
    page = await mt.get("/p/about", headers=A)
    assert page.status_code == 200, page.text
    assert _vary(page) == ["X-Inertia", "Cookie"]
    cached = await mt.get("/p/about", headers={**A, "If-None-Match": page.headers["etag"]})
    assert cached.status_code == 304
    assert _vary(cached) == ["X-Inertia", "Cookie"]
    sitemap = await mt.get("/sitemap.xml", headers=A)
    assert sitemap.status_code == 200
    assert sitemap.headers["cache-control"].startswith("public")
    assert _vary(sitemap) == ["Cookie"]


async def test_single_mode_vary_is_unchanged(authed_client: AsyncClient) -> None:
    created = await authed_client.post(API, json={"title": "Hi", "slug": "hi", "draft_data": {}})
    assert created.status_code == 201, created.text
    await authed_client.post(f"{API}/{created.json()['id']}/publish", json={})
    page = await authed_client.get("/p/hi")
    assert page.status_code == 200, page.text
    # ``Cookie`` here is SessionMiddleware's (the render read the session).
    assert page.headers["vary"] == "X-Inertia, Cookie"
    cached = await authed_client.get("/p/hi", headers={"If-None-Match": page.headers["etag"]})
    assert (cached.status_code, cached.headers.get("vary")) == (304, "X-Inertia")
    assert (await authed_client.get("/sitemap.xml")).headers.get("vary") is None


async def test_single_mode_stamps_the_default_tenant(authed_client: AsyncClient, db) -> None:
    created = await authed_client.post(API, json={"title": "Hi", "slug": "hi", "draft_data": {}})
    assert created.status_code == 201, created.text
    app = authed_client._transport.app  # type: ignore[attr-defined]
    from pagebuilder.models import Page
    from sqlalchemy import select

    async with app.state.sm.db.session_factory() as session:
        rows = (await session.execute(select(Page.tenant_id))).scalars().all()
    assert rows == ["default"]
