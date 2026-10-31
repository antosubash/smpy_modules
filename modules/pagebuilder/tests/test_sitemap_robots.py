"""Tests for /sitemap.xml and /robots.txt (issue #24)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_INERTIA_HEADERS = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


async def _create_and_publish(
    client: AsyncClient,
    *,
    slug: str,
    extra: dict | None = None,
) -> int:
    payload = {"title": slug, "slug": slug, "draft_data": {"content": []}}
    if extra:
        payload.update(extra)
    create = await client.post("/api/pagebuilder/pages", json=payload)
    assert create.status_code == 201, create.text
    page_id = create.json()["id"]
    publish = await client.post(f"/api/pagebuilder/pages/{page_id}/publish")
    assert publish.status_code == 200
    return page_id


async def test_sitemap_lists_published_pages(authed_client: AsyncClient) -> None:
    await _create_and_publish(authed_client, slug="hello")
    await _create_and_publish(authed_client, slug="world")
    response = await authed_client.get("/sitemap.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    body = response.text
    assert "<urlset" in body
    assert "/p/hello" in body
    assert "/p/world" in body


async def test_sitemap_excludes_drafts(authed_client: AsyncClient) -> None:
    # Create a draft page (not published).
    await authed_client.post(
        "/api/pagebuilder/pages",
        json={"title": "Draft", "slug": "draft", "draft_data": {}},
    )
    await _create_and_publish(authed_client, slug="live")
    response = await authed_client.get("/sitemap.xml")
    assert "/p/live" in response.text
    assert "/p/draft" not in response.text


async def test_sitemap_excludes_noindex_pages(authed_client: AsyncClient) -> None:
    await _create_and_publish(
        authed_client, slug="indexed", extra={"index_in_search": True}
    )
    await _create_and_publish(
        authed_client, slug="hidden", extra={"index_in_search": False}
    )
    response = await authed_client.get("/sitemap.xml")
    assert "/p/indexed" in response.text
    assert "/p/hidden" not in response.text


async def test_sitemap_empty_is_still_valid_xml(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/sitemap.xml")
    assert response.status_code == 200
    assert response.text.startswith('<?xml version="1.0"')
    assert "<urlset" in response.text
    assert "</urlset>" in response.text


async def test_sitemap_cache_control_header(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/sitemap.xml")
    assert "max-age=" in response.headers.get("Cache-Control", "")


async def test_robots_default_includes_sitemap_reference(
    authed_client: AsyncClient,
) -> None:
    response = await authed_client.get("/robots.txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "User-agent: *" in body
    assert "Allow: /" in body
    assert "Sitemap:" in body
    assert "/sitemap.xml" in body


async def test_robots_cache_control_header(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/robots.txt")
    assert "max-age=" in response.headers.get("Cache-Control", "")
