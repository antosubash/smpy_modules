"""``render_public_page(url_prefix=...)`` still works, and says it is deprecated.

The keyword belonged to the ``public_claims`` hook, removed in #132. It was in
the published API reference, so a host serving pages from its own router may
still pass it; removing it outright would turn that call into a ``TypeError``.
It keeps its old meaning — the canonical URL and the old-slug redirect target —
and warns.
"""

from __future__ import annotations

import warnings

import pytest
from fastapi import Depends, Request, Response
from httpx import AsyncClient
from pagebuilder.deps import get_settings
from pagebuilder.endpoints.public_views import render_public_page
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.tenancy import bind_public
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

API = "/api/pagebuilder/pages"
_INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


def _mount_elsewhere(client: AsyncClient, caught: list[warnings.WarningMessage]) -> None:
    """A host route serving pages at ``/elsewhere/{slug}``, as the old API
    reference told a claimant to write it."""

    async def elsewhere(
        slug: str,
        request: Request,
        inertia: InertiaDep,
        db: AsyncSession = Depends(get_db),
        settings: PagebuilderSettings = Depends(get_settings),
    ) -> Response:
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            response = await render_public_page(
                slug, request, inertia, db, settings, locale="en", url_prefix="/elsewhere"
            )
        caught.extend(seen)
        return response

    app = client._transport.app  # type: ignore[attr-defined]
    app.add_api_route(
        "/elsewhere/{slug}",
        elsewhere,
        methods=["GET"],
        response_model=None,
        dependencies=[Depends(bind_public)],
    )


async def _publish(client: AsyncClient, slug: str) -> int:
    created = await client.post(
        API, json={"title": slug, "slug": slug, "draft_data": {"content": []}}
    )
    assert created.status_code == 201, created.text
    page_id = created.json()["id"]
    assert (await client.post(f"{API}/{page_id}/publish")).status_code == 200
    return page_id


async def test_url_prefix_sets_the_canonical_and_warns(authed_client: AsyncClient) -> None:
    caught: list[warnings.WarningMessage] = []
    _mount_elsewhere(authed_client, caught)
    await _publish(authed_client, "hello")

    response = await authed_client.get("/elsewhere/hello", headers=_INERTIA)

    assert response.status_code == 200, response.text
    assert response.json()["props"]["canonical_url"].endswith("/elsewhere/hello")
    assert [w.category for w in caught] == [DeprecationWarning]
    assert "url_prefix" in str(caught[0].message)


async def test_url_prefix_is_where_an_old_slug_redirects(authed_client: AsyncClient) -> None:
    caught: list[warnings.WarningMessage] = []
    _mount_elsewhere(authed_client, caught)
    page_id = await _publish(authed_client, "old-name")
    renamed = await authed_client.put(f"{API}/{page_id}", json={"slug": "new-name"})
    assert renamed.status_code == 200, renamed.text
    assert (await authed_client.post(f"{API}/{page_id}/publish")).status_code == 200

    moved = await authed_client.get("/elsewhere/old-name", follow_redirects=False)

    assert moved.status_code == 301
    assert moved.headers["location"] == "/elsewhere/new-name"
    assert caught and all(w.category is DeprecationWarning for w in caught)


async def test_the_own_route_does_not_warn(authed_client: AsyncClient) -> None:
    await _publish(authed_client, "plain")

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        response = await authed_client.get("/p/plain", headers=_INERTIA)

    assert response.status_code == 200
    assert response.json()["props"]["canonical_url"].endswith("/p/plain")
