from __future__ import annotations

import pytest

# Imported from `conftest`, not `tests.conftest`: with an editable
# framework checkout on sys.path (make link-framework) the bare `tests`
# package is ambiguous and resolves to the framework's own.
from conftest import create_draft
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


_HEADER_DATA = {
    "content": [
        {
            "type": "Heading",
            "props": {"id": "site-title", "text": "Acme", "level": "h2"},
        }
    ],
    "root": {"props": {}},
}

_FOOTER_DATA = {
    "content": [
        {
            "type": "Text",
            "props": {"id": "copyright", "text": "© 2026 Acme."},
        }
    ],
    "root": {"props": {}},
}


async def _publish_page(client: AsyncClient, slug: str = "home") -> dict:
    page = await create_draft(
        client,
        slug=slug,
        title="Home",
        draft_data={
            "content": [{"type": "Text", "props": {"id": "body", "text": "Body"}}],
            "root": {"props": {}},
        },
    )
    publish = await client.post(f"/api/pagebuilder/pages/{page['id']}/publish")
    assert publish.status_code == 200
    return page


async def test_get_layout_lazily_creates_singleton(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/api/pagebuilder/layout")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] is not None
    assert body["header_data"] == {}
    assert body["footer_data"] == {}


async def test_get_layout_is_idempotent(authed_client: AsyncClient) -> None:
    first = (await authed_client.get("/api/pagebuilder/layout")).json()
    second = (await authed_client.get("/api/pagebuilder/layout")).json()
    assert first["id"] == second["id"]


async def test_put_layout_persists_both_slots(authed_client: AsyncClient) -> None:
    response = await authed_client.put(
        "/api/pagebuilder/layout",
        json={"header_data": _HEADER_DATA, "footer_data": _FOOTER_DATA},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["header_data"] == _HEADER_DATA
    assert body["footer_data"] == _FOOTER_DATA


async def test_put_layout_partial_only_touches_provided_keys(
    authed_client: AsyncClient,
) -> None:
    await authed_client.put(
        "/api/pagebuilder/layout",
        json={"header_data": _HEADER_DATA, "footer_data": _FOOTER_DATA},
    )
    response = await authed_client.put(
        "/api/pagebuilder/layout",
        json={"header_data": {"content": [], "root": {"props": {}}}},
    )
    body = response.json()
    assert body["header_data"]["content"] == []
    assert body["footer_data"] == _FOOTER_DATA


async def test_put_layout_records_a_revision(authed_client: AsyncClient) -> None:
    await authed_client.put(
        "/api/pagebuilder/layout",
        json={"header_data": _HEADER_DATA, "note": "Initial"},
    )
    await authed_client.put(
        "/api/pagebuilder/layout",
        json={"header_data": _FOOTER_DATA, "note": "Swap"},
    )
    revisions = (await authed_client.get("/api/pagebuilder/layout/revisions")).json()[
        "items"
    ]
    assert [r["note"] for r in revisions] == ["Swap", "Initial"]


async def test_put_layout_skips_revision_when_unchanged(
    authed_client: AsyncClient,
) -> None:
    """A no-op save must not pollute history — save-button-spam is real."""
    await authed_client.put(
        "/api/pagebuilder/layout",
        json={"header_data": _HEADER_DATA, "note": "v1"},
    )
    await authed_client.put(
        "/api/pagebuilder/layout",
        json={"header_data": _HEADER_DATA, "note": "noop"},
    )
    revisions = (await authed_client.get("/api/pagebuilder/layout/revisions")).json()[
        "items"
    ]
    assert [r["note"] for r in revisions] == ["v1"]


async def test_layout_restore_round_trips_both_slots(
    authed_client: AsyncClient,
) -> None:
    """Restore replays both slots atomically even when only one slot has changed since."""
    await authed_client.put(
        "/api/pagebuilder/layout",
        json={
            "header_data": _HEADER_DATA,
            "footer_data": _FOOTER_DATA,
            "note": "v1",
        },
    )
    revisions = (await authed_client.get("/api/pagebuilder/layout/revisions")).json()[
        "items"
    ]
    target_id = revisions[0]["id"]

    await authed_client.put(
        "/api/pagebuilder/layout",
        json={"header_data": {"content": [], "root": {"props": {}}}, "note": "wiped"},
    )

    restore = await authed_client.post(
        f"/api/pagebuilder/layout/revisions/{target_id}/restore"
    )
    assert restore.status_code == 200, restore.text
    body = restore.json()
    assert body["header_data"] == _HEADER_DATA
    assert body["footer_data"] == _FOOTER_DATA


async def test_put_layout_requires_edit_permission(
    client: AsyncClient,
) -> None:
    response = await client.put(
        "/api/pagebuilder/layout",
        json={"header_data": _HEADER_DATA},
    )
    assert response.status_code == 401


async def test_public_viewer_renders_layout_props_when_set(
    authed_client: AsyncClient,
) -> None:
    await authed_client.put(
        "/api/pagebuilder/layout",
        json={"header_data": _HEADER_DATA, "footer_data": _FOOTER_DATA},
    )
    page = await _publish_page(authed_client)
    response = await authed_client.get(
        f"/p/{page['slug']}", headers={"X-Inertia": "true"}
    )
    assert response.status_code == 200
    props = response.json()["props"]
    assert props["layout_header"] == _HEADER_DATA
    assert props["layout_footer"] == _FOOTER_DATA


async def test_public_viewer_skips_empty_slots(
    authed_client: AsyncClient,
) -> None:
    """Empty slots surface as None so the React side drops the wrapper."""
    await authed_client.put(
        "/api/pagebuilder/layout",
        json={
            "header_data": {"content": [], "root": {"props": {}}},
            "footer_data": _FOOTER_DATA,
        },
    )
    page = await _publish_page(authed_client)
    response = await authed_client.get(
        f"/p/{page['slug']}", headers={"X-Inertia": "true"}
    )
    props = response.json()["props"]
    assert props["layout_header"] is None
    assert props["layout_footer"] == _FOOTER_DATA


async def test_public_viewer_renders_pages_when_layout_unset(
    authed_client: AsyncClient,
) -> None:
    page = await _publish_page(authed_client, slug="bare")
    response = await authed_client.get(
        f"/p/{page['slug']}", headers={"X-Inertia": "true"}
    )
    props = response.json()["props"]
    assert props["layout_header"] is None
    assert props["layout_footer"] is None


async def test_layout_edit_takes_effect_without_republishing_each_page(
    authed_client: AsyncClient,
) -> None:
    """Acceptance criterion: edits propagate without re-publishing each page."""
    page_a = await _publish_page(authed_client, slug="a")
    page_b = await _publish_page(authed_client, slug="b")
    await authed_client.put(
        "/api/pagebuilder/layout",
        json={"header_data": _HEADER_DATA},
    )
    for slug in (page_a["slug"], page_b["slug"]):
        response = await authed_client.get(f"/p/{slug}", headers={"X-Inertia": "true"})
        assert response.json()["props"]["layout_header"] == _HEADER_DATA


async def test_layout_edit_invalidates_page_etag(
    authed_client: AsyncClient,
) -> None:
    """Layout changes must bust the page ETag — otherwise clients keep
    serving stale chrome from cache."""
    page = await _publish_page(authed_client)
    first = await authed_client.get(f"/p/{page['slug']}")
    etag_before = first.headers.get("etag")
    assert etag_before

    await authed_client.put(
        "/api/pagebuilder/layout",
        json={"header_data": _HEADER_DATA},
    )
    second = await authed_client.get(f"/p/{page['slug']}")
    etag_after = second.headers.get("etag")
    assert etag_after and etag_after != etag_before


async def test_layout_revision_carries_combined_snapshot(
    authed_client: AsyncClient,
) -> None:
    await authed_client.put(
        "/api/pagebuilder/layout",
        json={"header_data": _HEADER_DATA, "footer_data": _FOOTER_DATA},
    )
    revisions = (await authed_client.get("/api/pagebuilder/layout/revisions")).json()[
        "items"
    ]
    detail = await authed_client.get(
        f"/api/pagebuilder/layout/revisions/{revisions[0]['id']}"
    )
    body = detail.json()
    assert body["header_data"] == _HEADER_DATA
    assert body["footer_data"] == _FOOTER_DATA
