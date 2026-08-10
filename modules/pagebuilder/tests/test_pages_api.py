"""Integration tests for the pages JSON API (issue #29)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _create(client: AsyncClient, *, slug: str = "about", title: str = "About") -> dict:
    response = await client.post(
        "/api/pagebuilder/pages",
        json={"title": title, "slug": slug, "draft_data": {"content": []}},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_list_pages_starts_empty(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/api/pagebuilder/pages")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


async def test_create_and_get_page(authed_client: AsyncClient) -> None:
    created = await _create(authed_client)
    assert created["slug"] == "about"
    assert created["status"] == "draft"
    assert created["has_published"] is False
    response = await authed_client.get(f"/api/pagebuilder/pages/{created['id']}")
    assert response.status_code == 200
    assert response.json()["slug"] == "about"


async def test_create_rejects_invalid_slug(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/pagebuilder/pages",
        json={"title": "Bad", "slug": "Has Spaces", "draft_data": {}},
    )
    assert response.status_code == 422


async def test_create_returns_409_on_slug_collision(authed_client: AsyncClient) -> None:
    await _create(authed_client, slug="dup")
    response = await authed_client.post(
        "/api/pagebuilder/pages",
        json={"title": "Other", "slug": "dup", "draft_data": {}},
    )
    assert response.status_code == 409


async def test_update_page(authed_client: AsyncClient) -> None:
    page = await _create(authed_client)
    response = await authed_client.put(
        f"/api/pagebuilder/pages/{page['id']}",
        json={"title": "Renamed", "meta_description": "New desc"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renamed"
    assert body["meta_description"] == "New desc"


async def test_update_409_on_slug_collision(authed_client: AsyncClient) -> None:
    await _create(authed_client, slug="alpha", title="Alpha")
    bravo = await _create(authed_client, slug="bravo", title="Bravo")
    response = await authed_client.put(
        f"/api/pagebuilder/pages/{bravo['id']}",
        json={"slug": "alpha"},
    )
    assert response.status_code == 409


async def test_get_unknown_page_returns_404(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/api/pagebuilder/pages/9999")
    assert response.status_code == 404


async def test_publish_and_unpublish_round_trip(authed_client: AsyncClient) -> None:
    page = await _create(authed_client)

    pub = await authed_client.post(f"/api/pagebuilder/pages/{page['id']}/publish")
    assert pub.status_code == 200
    assert pub.json()["status"] == "published"
    assert pub.json()["has_published"] is True

    unpub = await authed_client.post(f"/api/pagebuilder/pages/{page['id']}/unpublish")
    assert unpub.status_code == 200
    assert unpub.json()["status"] == "draft"
    # Unpublish keeps the snapshot so re-publish without a draft change still works.
    assert unpub.json()["has_published"] is True


async def test_delete_page(authed_client: AsyncClient) -> None:
    page = await _create(authed_client)
    response = await authed_client.delete(f"/api/pagebuilder/pages/{page['id']}")
    assert response.status_code == 204
    assert (
        await authed_client.get(f"/api/pagebuilder/pages/{page['id']}")
    ).status_code == 404
