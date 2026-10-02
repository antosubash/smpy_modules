"""Integration tests for the ``/p/{slug}`` public viewer (issue #29).

Headers (CSP / Cache-Control / ETag) are unit-tested in
``test_public_view_headers.py``; this file exercises them end-to-end
against an actual HTTP round-trip plus the 404-on-unpublished and
304-on-If-None-Match flows the issue called out.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


_INERTIA_HEADERS = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


async def _create_published(client: AsyncClient, slug: str = "hello") -> int:
    response = await client.post(
        "/api/pagebuilder/pages",
        json={
            "title": "Hello",
            "slug": slug,
            "draft_data": {"content": ["body"]},
        },
    )
    assert response.status_code == 201, response.text
    page_id = response.json()["id"]
    pub = await client.post(f"/api/pagebuilder/pages/{page_id}/publish")
    assert pub.status_code == 200
    return page_id


async def test_unpublished_page_returns_404(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/pagebuilder/pages",
        json={"title": "Draft", "slug": "draft-page", "draft_data": {}},
    )
    assert response.status_code == 201
    public = await authed_client.get("/p/draft-page", headers=_INERTIA_HEADERS)
    assert public.status_code == 404


async def test_missing_slug_returns_404(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/p/nope", headers=_INERTIA_HEADERS)
    assert response.status_code == 404


async def test_published_page_renders_with_headers(authed_client: AsyncClient) -> None:
    await _create_published(authed_client)
    response = await authed_client.get("/p/hello", headers=_INERTIA_HEADERS)
    assert response.status_code == 200
    assert response.headers.get("ETag", "").startswith('W/"')
    cache_control = response.headers["Cache-Control"]
    assert "public" in cache_control
    assert "max-age=" in cache_control
    assert response.headers.get("Content-Security-Policy", "").startswith("default-src 'self'")


async def test_published_page_unpublishes_to_404(authed_client: AsyncClient) -> None:
    page_id = await _create_published(authed_client)
    await authed_client.post(f"/api/pagebuilder/pages/{page_id}/unpublish")
    response = await authed_client.get("/p/hello", headers=_INERTIA_HEADERS)
    assert response.status_code == 404


async def test_if_none_match_returns_304(authed_client: AsyncClient) -> None:
    await _create_published(authed_client)
    first = await authed_client.get("/p/hello", headers=_INERTIA_HEADERS)
    etag = first.headers["ETag"]

    second = await authed_client.get(
        "/p/hello",
        headers={**_INERTIA_HEADERS, "If-None-Match": etag},
    )
    assert second.status_code == 304
    assert second.headers["ETag"] == etag


async def test_the_page_etag_does_not_validate_an_in_app_visit(
    authed_client: AsyncClient,
) -> None:
    """A browser holding the full page must not get a 304 for Inertia's JSON:
    it would hand Inertia the cached HTML and the visit would fail."""
    await _create_published(authed_client)
    page = await authed_client.get("/p/hello")
    assert "X-Inertia" in page.headers["Vary"]

    visit = await authed_client.get(
        "/p/hello",
        headers={**_INERTIA_HEADERS, "If-None-Match": page.headers["ETag"]},
    )

    assert visit.status_code == 200
    assert visit.headers["ETag"] != page.headers["ETag"]
