"""Tests for opt-in admin auth gating (issue #7).

The acceptance criterion: hitting ``/api/pagebuilder/pages`` on a host
without a logged-in user returns 401. The ``client`` fixture has
``requires_auth=True`` and no user injection, so we verify both the
401 baseline and that flipping the setting (``open_client``) skips it.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_api_returns_401_without_user(client: AsyncClient) -> None:
    response = await client.get("/api/pagebuilder/pages")
    assert response.status_code == 401


async def test_create_returns_401_without_user(client: AsyncClient) -> None:
    response = await client.post(
        "/api/pagebuilder/pages",
        json={"title": "x", "slug": "x", "draft_data": {}},
    )
    assert response.status_code == 401


async def test_uploads_listing_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/pagebuilder/uploads")
    assert response.status_code == 401


async def test_public_viewer_is_anonymous(client: AsyncClient) -> None:
    """The public router must NOT be gated by the admin auth dep."""
    # No page exists, so we expect 404 (not 401) — proving the dep didn't fire.
    response = await client.get(
        "/p/anything", headers={"X-Inertia": "true", "X-Inertia-Version": "1.0"}
    )
    assert response.status_code == 404


async def test_open_client_bypasses_auth(open_client: AsyncClient) -> None:
    """With ``requires_auth=False`` admin routes are reachable anonymously."""
    response = await open_client.get("/api/pagebuilder/pages")
    assert response.status_code == 200


async def test_authed_client_passes(authed_client: AsyncClient) -> None:
    """Sanity-check the auth-override fixture for the rest of the suite."""
    response = await authed_client.get("/api/pagebuilder/pages")
    assert response.status_code == 200
