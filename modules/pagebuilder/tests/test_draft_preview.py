"""The draft preview route behind the narrow editor's "Preview" button.

Below 900px the canvas is read-only, so previewing is most of what the screen
can still do — which only helps if the preview shows the *draft*. The published
URL cannot answer that question, and a preview rendered by a second renderer
could disagree with the real page, so this route reuses the public component.
"""

from __future__ import annotations

from httpx import AsyncClient

API = "/api/pagebuilder/pages"

INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}

DRAFT_BODY = {
    "content": [{"type": "Heading", "props": {"id": "h1", "text": "Only in the draft"}}],
    "root": {"props": {"title": "Preview me", "width": "contained"}},
}


async def _create(client: AsyncClient, slug: str) -> int:
    response = await client.post(
        API, json={"title": "Preview me", "slug": slug, "draft_data": DRAFT_BODY}
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def test_preview_renders_the_draft_body(authed_client: AsyncClient) -> None:
    page_id = await _create(authed_client, "preview-draft")

    response = await authed_client.get(f"/pagebuilder/{page_id}/preview", headers=INERTIA)

    assert response.status_code == 200, response.text
    props = response.json()["props"]
    assert props["data"] == DRAFT_BODY


async def test_preview_shows_edits_the_published_page_has_not_seen(
    authed_client: AsyncClient,
) -> None:
    """The whole reason the route exists rather than linking to ``/p/{slug}``."""
    page_id = await _create(authed_client, "preview-ahead")
    await authed_client.post(f"{API}/{page_id}/publish", json={})

    changed = {
        "content": [{"type": "Heading", "props": {"id": "h1", "text": "Newer than live"}}],
        "root": {"props": {"title": "Preview me", "width": "contained"}},
    }
    saved = await authed_client.put(f"{API}/{page_id}", json={"draft_data": changed})
    assert saved.status_code == 200, saved.text

    response = await authed_client.get(f"/pagebuilder/{page_id}/preview", headers=INERTIA)
    assert response.json()["props"]["data"] == changed

    live = await authed_client.get("/p/preview-ahead", headers=INERTIA)
    assert live.json()["props"]["data"] != changed


async def test_preview_is_never_indexable(authed_client: AsyncClient) -> None:
    """Even when the page itself is set to be indexed.

    A preview URL that gets indexed in place of the real one is the one
    failure here that would be hard to undo.
    """
    page_id = await _create(authed_client, "preview-noindex")
    assert (await authed_client.get(f"{API}/{page_id}")).json()["index_in_search"] is True

    response = await authed_client.get(f"/pagebuilder/{page_id}/preview", headers=INERTIA)

    props = response.json()["props"]
    assert props["index_in_search"] is False
    # A canonical pointing anywhere would hand the preview a second identity.
    assert props["canonical_url"] is None


async def test_preview_requires_a_session(client: AsyncClient) -> None:
    response = await client.get("/pagebuilder/1/preview", headers=INERTIA)
    assert response.status_code == 401


async def test_preview_of_a_missing_page_is_404(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/pagebuilder/999999/preview", headers=INERTIA)
    assert response.status_code == 404


async def test_preview_does_not_shadow_the_media_routes(authed_client: AsyncClient) -> None:
    """``/pagebuilder/{page_id}/preview`` sits next to ``/media/{asset_id}``."""
    response = await authed_client.get("/pagebuilder/media", headers=INERTIA)
    assert response.status_code == 200, response.text
