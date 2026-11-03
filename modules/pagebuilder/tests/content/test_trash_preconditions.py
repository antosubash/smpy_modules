"""Restore and purge only apply to pages that are actually in the trash.

Both read the page with ``include_trashed=True``, which suppresses the rule
that trashed pages 404 — it does not assert the page *is* trashed. Without a
second check, the two most consequential operations in the module accept any
page id at all:

* ``purge`` permanently deletes a live page, its revisions and its redirects,
  and announces ``PageDeleted`` so every other module drops its own row. There
  is no undo; the retention window is the whole point and it is skipped.
* ``restore`` force-unpublishes a live page, because setting the status to
  DRAFT is not a no-op even when clearing ``deleted_at`` is.

Both are reachable over HTTP with nothing but ``news.edit``/``pagebuilder``
edit rights, from a mistyped id or a stale button.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

API = "/api/pagebuilder/pages"


async def _live_page(client: AsyncClient, slug: str) -> int:
    created = await client.post(
        API, json={"title": "Live", "slug": slug, "draft_data": {"content": []}}
    )
    assert created.status_code == 201, created.text
    page_id = int(created.json()["id"])
    published = await client.post(f"{API}/{page_id}/publish", json={})
    assert published.status_code == 200, published.text
    return page_id


async def test_purging_a_live_page_is_refused(authed_client: AsyncClient) -> None:
    """The one that cannot be undone."""
    page_id = await _live_page(authed_client, "purge-guard")

    refused = await authed_client.delete(f"{API}/{page_id}/purge")

    assert refused.status_code == 404, refused.text
    still_there = await authed_client.get(f"{API}/{page_id}")
    assert still_there.status_code == 200, "purge deleted a page that was never trashed"
    assert still_there.json()["status"] == "published"


async def test_restoring_a_live_page_is_refused(authed_client: AsyncClient) -> None:
    """Clearing deleted_at is a no-op here; dropping it to DRAFT is not."""
    page_id = await _live_page(authed_client, "restore-guard")

    refused = await authed_client.post(f"{API}/{page_id}/restore", json={})

    assert refused.status_code == 404, refused.text
    unchanged = await authed_client.get(f"{API}/{page_id}")
    assert unchanged.json()["status"] == "published", (
        "restore unpublished a page that was never trashed"
    )


async def test_purging_a_draft_that_was_never_trashed_is_refused(
    authed_client: AsyncClient,
) -> None:
    """Not only published pages — an unsaved draft is someone's work too."""
    created = await authed_client.post(
        API, json={"title": "Draft", "slug": "purge-draft-guard", "draft_data": {}}
    )
    page_id = int(created.json()["id"])

    refused = await authed_client.delete(f"{API}/{page_id}/purge")

    assert refused.status_code == 404, refused.text
    assert (await authed_client.get(f"{API}/{page_id}")).status_code == 200


async def test_the_real_trash_round_trip_still_works(
    authed_client: AsyncClient,
) -> None:
    """The guard must not break what the trash screen actually does."""
    page_id = await _live_page(authed_client, "round-trip")

    assert (await authed_client.delete(f"{API}/{page_id}")).status_code == 204
    restored = await authed_client.post(f"{API}/{page_id}/restore", json={})
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "draft"

    # And a genuinely trashed page still purges.
    assert (await authed_client.delete(f"{API}/{page_id}")).status_code == 204
    assert (await authed_client.delete(f"{API}/{page_id}/purge")).status_code == 204
    assert (await authed_client.get(f"{API}/{page_id}")).status_code == 404
