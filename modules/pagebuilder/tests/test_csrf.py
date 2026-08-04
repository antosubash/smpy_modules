"""Tests for CSRF token enforcement (issue #10).

Acceptance criteria: ``POST`` without ``X-CSRF-Token`` returns 403; with
a token bound to the session it returns 200.

The token is set on every admin Inertia view response (both as an
Inertia shared prop and as a ``pagebuilder_csrf`` cookie). For these
tests we hit the admin index first to bootstrap the session + cookie,
then send the mutating request with the captured token.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_INERTIA_HEADERS = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


async def _bootstrap_csrf(client: AsyncClient) -> str:
    """Hit an admin view so the CSRF cookie is set; return the token."""
    response = await client.get("/pagebuilder/", headers=_INERTIA_HEADERS)
    assert response.status_code == 200, response.text
    token = response.cookies.get("pagebuilder_csrf")
    assert token, "CSRF cookie not set by admin view"
    return token


async def test_mutation_without_token_returns_403(csrf_client: AsyncClient) -> None:
    await _bootstrap_csrf(csrf_client)
    response = await csrf_client.post(
        "/api/pagebuilder/pages",
        json={"title": "no token", "slug": "no-token", "draft_data": {}},
    )
    assert response.status_code == 403


async def test_mutation_with_wrong_token_returns_403(csrf_client: AsyncClient) -> None:
    await _bootstrap_csrf(csrf_client)
    response = await csrf_client.post(
        "/api/pagebuilder/pages",
        json={"title": "wrong", "slug": "wrong-token", "draft_data": {}},
        headers={"X-CSRF-Token": "obviously-not-the-real-token"},
    )
    assert response.status_code == 403


async def test_mutation_with_valid_token_succeeds(csrf_client: AsyncClient) -> None:
    token = await _bootstrap_csrf(csrf_client)
    response = await csrf_client.post(
        "/api/pagebuilder/pages",
        json={"title": "ok", "slug": "ok", "draft_data": {}},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 201, response.text


async def test_safe_methods_skip_csrf(csrf_client: AsyncClient) -> None:
    await _bootstrap_csrf(csrf_client)
    response = await csrf_client.get("/api/pagebuilder/pages")
    assert response.status_code == 200


async def test_csrf_disabled_passes_without_token(authed_client: AsyncClient) -> None:
    """``csrf_protect=False`` (the default in ``authed_client``) lets POSTs
    through with no token at all."""
    response = await authed_client.post(
        "/api/pagebuilder/pages",
        json={"title": "no csrf", "slug": "no-csrf", "draft_data": {}},
    )
    assert response.status_code == 201
