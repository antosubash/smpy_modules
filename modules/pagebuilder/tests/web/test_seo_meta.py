"""Tests for SEO meta fields on the public viewer (issues #23, #25).

Covers the inertia props the page render emits — the front-end then
maps those onto ``<link rel="canonical">``, ``<meta name="robots">``,
the JSON-LD ``<script>``, and the og:url / og:site_name / twitter:site
tags. The inertia JSON response shape exposes the props directly so we
can assert without a DOM.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_INERTIA_HEADERS = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


async def _create_and_publish(
    client: AsyncClient,
    *,
    slug: str = "hello",
    extra: dict | None = None,
) -> int:
    payload = {
        "title": "Hello",
        "slug": slug,
        "draft_data": {"content": []},
    }
    if extra:
        payload.update(extra)
    create = await client.post("/api/pagebuilder/pages", json=payload)
    assert create.status_code == 201, create.text
    page_id = create.json()["id"]
    publish = await client.post(f"/api/pagebuilder/pages/{page_id}/publish")
    assert publish.status_code == 200
    return page_id


async def test_canonical_defaults_to_own_url(authed_client: AsyncClient) -> None:
    await _create_and_publish(authed_client)
    response = await authed_client.get("/p/hello", headers=_INERTIA_HEADERS)
    assert response.status_code == 200
    props = response.json()["props"]
    assert props["canonical_url"].endswith("/p/hello")
    assert props["og_url"] == props["canonical_url"]


async def test_canonical_override_is_used(authed_client: AsyncClient) -> None:
    await _create_and_publish(
        authed_client,
        extra={"canonical_url": "https://example.com/canonical"},
    )
    response = await authed_client.get("/p/hello", headers=_INERTIA_HEADERS)
    props = response.json()["props"]
    assert props["canonical_url"] == "https://example.com/canonical"


async def test_index_in_search_default_true(authed_client: AsyncClient) -> None:
    await _create_and_publish(authed_client)
    response = await authed_client.get("/p/hello", headers=_INERTIA_HEADERS)
    props = response.json()["props"]
    assert props["index_in_search"] is True


async def test_noindex_flag_propagates(authed_client: AsyncClient) -> None:
    await _create_and_publish(authed_client, extra={"index_in_search": False})
    response = await authed_client.get("/p/hello", headers=_INERTIA_HEADERS)
    props = response.json()["props"]
    assert props["index_in_search"] is False


async def test_json_ld_round_trips(authed_client: AsyncClient) -> None:
    doc = {"@context": "https://schema.org", "@type": "Article", "name": "Hello"}
    await _create_and_publish(authed_client, extra={"json_ld": doc})
    response = await authed_client.get("/p/hello", headers=_INERTIA_HEADERS)
    props = response.json()["props"]
    assert props["json_ld"] == doc


async def test_json_ld_omitted_when_unset(authed_client: AsyncClient) -> None:
    await _create_and_publish(authed_client)
    response = await authed_client.get("/p/hello", headers=_INERTIA_HEADERS)
    props = response.json()["props"]
    assert props["json_ld"] is None


async def test_site_name_and_twitter_handle_blank_by_default(
    authed_client: AsyncClient,
) -> None:
    """Issue #25: no settings → no tags. Empty props avoid empty meta tags."""
    await _create_and_publish(authed_client)
    response = await authed_client.get("/p/hello", headers=_INERTIA_HEADERS)
    props = response.json()["props"]
    assert props["site_name"] is None
    assert props["twitter_handle"] is None
