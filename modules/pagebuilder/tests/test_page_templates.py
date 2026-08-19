"""Starting points and breadcrumb parents — what the New page dialog needs.

The behaviour worth pinning is that a copy is a *copy*: a template is an
ordinary page, so the obvious implementation (share the dict) would let editing
the new page rewrite the template it came from.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

HERO = {"content": [{"type": "Heading", "props": {"id": "h", "text": "Hero"}}], "root": {}}


async def _create(client: AsyncClient, **body) -> dict:
    payload = {"title": "A page", "slug": "a-page", "draft_data": {"content": []}, **body}
    response = await client.post("/api/pagebuilder/pages", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


class TestTemplates:
    async def test_a_new_page_is_not_a_template(self, authed_client: AsyncClient) -> None:
        assert (await _create(authed_client))["is_template"] is False

    async def test_only_flagged_pages_are_offered_as_starting_points(
        self, authed_client: AsyncClient
    ) -> None:
        await _create(authed_client, slug="ordinary", title="Ordinary")
        await _create(authed_client, slug="starter", title="Starter", is_template=True)

        listed = (await authed_client.get("/api/pagebuilder/pages/templates")).json()

        assert [p["slug"] for p in listed["items"]] == ["starter"]

    async def test_an_existing_page_can_be_promoted_to_a_template(
        self, authed_client: AsyncClient
    ) -> None:
        """2h's "Save as template" — the flag is an ordinary field update."""
        page = await _create(authed_client, slug="promote", title="Promote")

        await authed_client.put(
            f"/api/pagebuilder/pages/{page['id']}", json={"is_template": True}
        )

        listed = (await authed_client.get("/api/pagebuilder/pages/templates")).json()
        assert [p["slug"] for p in listed["items"]] == ["promote"]

    async def test_templates_route_is_not_read_as_a_page_id(
        self, authed_client: AsyncClient
    ) -> None:
        """Declared above /pages/{page_id}, or "templates" 422s as an int."""
        assert (await authed_client.get("/api/pagebuilder/pages/templates")).status_code == 200


class TestCopyFrom:
    async def test_content_is_copied_from_the_source(self, authed_client: AsyncClient) -> None:
        source = await _create(authed_client, slug="source", title="Source", draft_data=HERO)

        copy = await _create(
            authed_client, slug="copy", title="Copy", copy_from_page_id=source["id"]
        )

        assert copy["draft_data"] == HERO

    async def test_the_copy_is_independent_of_its_source(
        self, authed_client: AsyncClient
    ) -> None:
        """The bug a shared dict would cause: editing one rewrites the other."""
        source = await _create(authed_client, slug="src2", title="Src", draft_data=HERO)
        copy = await _create(
            authed_client, slug="copy2", title="Copy", copy_from_page_id=source["id"]
        )

        await authed_client.put(
            f"/api/pagebuilder/pages/{copy['id']}",
            json={"draft_data": {"content": [], "root": {}}},
        )

        back = (await authed_client.get(f"/api/pagebuilder/pages/{source['id']}")).json()
        assert back["draft_data"] == HERO

    async def test_copying_carries_no_published_state(
        self, authed_client: AsyncClient
    ) -> None:
        """A starting point offers work in progress, not a live page."""
        source = await _create(authed_client, slug="src3", title="Src", draft_data=HERO)
        await authed_client.post(f"/api/pagebuilder/pages/{source['id']}/publish", json={})

        copy = await _create(
            authed_client, slug="copy3", title="Copy", copy_from_page_id=source["id"]
        )

        assert copy["status"] == "draft"
        assert copy["has_published"] is False

    async def test_copying_a_missing_page_is_a_404(self, authed_client: AsyncClient) -> None:
        response = await authed_client.post(
            "/api/pagebuilder/pages",
            json={
                "title": "Nope",
                "slug": "nope",
                "draft_data": {"content": []},
                "copy_from_page_id": 999_999,
            },
        )
        assert response.status_code == 404


class TestParent:
    async def test_parent_is_stored_and_read_back(self, authed_client: AsyncClient) -> None:
        parent = await _create(authed_client, slug="parent", title="Parent")

        child = await _create(
            authed_client, slug="child", title="Child", parent_id=parent["id"]
        )

        assert child["parent_id"] == parent["id"]

    async def test_parent_does_not_change_the_public_url(
        self, authed_client: AsyncClient
    ) -> None:
        """The whole point of it being breadcrumb-only: re-parenting for
        navigation must never break a link that already exists."""
        parent = await _create(authed_client, slug="p2", title="Parent")
        child = await _create(authed_client, slug="c2", title="Child", parent_id=parent["id"])
        await authed_client.post(f"/api/pagebuilder/pages/{child['id']}/publish", json={})

        assert (await authed_client.get("/p/c2")).status_code == 200

    async def test_deleting_a_parent_orphans_rather_than_cascades(
        self, authed_client: AsyncClient
    ) -> None:
        parent = await _create(authed_client, slug="p3", title="Parent")
        child = await _create(authed_client, slug="c3", title="Child", parent_id=parent["id"])

        await authed_client.delete(f"/api/pagebuilder/pages/{parent['id']}")

        back = await authed_client.get(f"/api/pagebuilder/pages/{child['id']}")
        assert back.status_code == 200
        assert back.json()["parent_id"] is None
