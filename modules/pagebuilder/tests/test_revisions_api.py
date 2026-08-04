"""Integration tests for revisions (issue #29).

Covers the publish → revision side-effect documented in PR #3.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _create_and_publish(client: AsyncClient, slug: str = "post") -> int:
    created = await client.post(
        "/api/pagebuilder/pages",
        json={
            "title": "First",
            "slug": slug,
            "meta_description": "v1 description",
            "draft_data": {"content": ["one"]},
        },
    )
    assert created.status_code == 201, created.text
    page_id = created.json()["id"]
    pub = await client.post(f"/api/pagebuilder/pages/{page_id}/publish")
    assert pub.status_code == 200
    return page_id


async def test_publish_appends_a_revision(authed_client: AsyncClient) -> None:
    page_id = await _create_and_publish(authed_client)
    response = await authed_client.get(f"/api/pagebuilder/pages/{page_id}/revisions")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "First"


async def test_multiple_publishes_accumulate_revisions(authed_client: AsyncClient) -> None:
    page_id = await _create_and_publish(authed_client)
    # Bump the draft and publish again.
    await authed_client.put(
        f"/api/pagebuilder/pages/{page_id}",
        json={"title": "Second"},
    )
    await authed_client.post(f"/api/pagebuilder/pages/{page_id}/publish")

    response = await authed_client.get(f"/api/pagebuilder/pages/{page_id}/revisions")
    items = response.json()["items"]
    # Service orders desc by id, so the newest revision is first.
    assert [r["title"] for r in items] == ["Second", "First"]


async def test_get_revision_detail(authed_client: AsyncClient) -> None:
    page_id = await _create_and_publish(authed_client)
    revisions = (await authed_client.get(f"/api/pagebuilder/pages/{page_id}/revisions")).json()
    revision_id = revisions["items"][0]["id"]
    response = await authed_client.get(
        f"/api/pagebuilder/pages/{page_id}/revisions/{revision_id}"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"content": ["one"]}


async def test_get_revision_404_when_belongs_to_another_page(
    authed_client: AsyncClient,
) -> None:
    a = await _create_and_publish(authed_client, slug="alpha")
    b = await _create_and_publish(authed_client, slug="bravo")
    b_revs = (await authed_client.get(f"/api/pagebuilder/pages/{b}/revisions")).json()
    b_revision_id = b_revs["items"][0]["id"]
    # Cross-reference: page A asking for B's revision should 404.
    response = await authed_client.get(
        f"/api/pagebuilder/pages/{a}/revisions/{b_revision_id}"
    )
    assert response.status_code == 404


async def test_restore_revision_overwrites_draft_only(
    authed_client: AsyncClient,
) -> None:
    page_id = await _create_and_publish(authed_client)
    # Mutate the draft so we can verify the restore actually overwrites it.
    await authed_client.put(
        f"/api/pagebuilder/pages/{page_id}",
        json={"title": "Changed", "draft_data": {"content": ["dirty"]}},
    )
    revisions = (await authed_client.get(f"/api/pagebuilder/pages/{page_id}/revisions")).json()
    revision_id = revisions["items"][0]["id"]

    restored = await authed_client.post(
        f"/api/pagebuilder/pages/{page_id}/revisions/{revision_id}/restore"
    )
    assert restored.status_code == 200
    body = restored.json()
    assert body["title"] == "First"  # restored from revision
    assert body["draft_data"] == {"content": ["one"]}
    # Status stays published (restore writes draft only, doesn't re-publish).
    assert body["status"] == "published"
