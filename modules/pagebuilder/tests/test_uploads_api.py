"""Integration tests for the media upload API (issue #29).

Complements ``test_media_security.py`` (which unit-tests the sniffer in
isolation) by exercising the full HTTP round-trip: multipart parsing,
the auth/CSRF gate, and the listing + delete endpoints.
"""

from __future__ import annotations

import pytest

# Imported from `conftest`, not `tests.conftest`: with an editable
# framework checkout on sys.path (make link-framework) the bare `tests`
# package is ambiguous and resolves to the framework's own.
from conftest import PNG_BYTES
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _upload(
    client: AsyncClient,
    *,
    filename: str = "hero.png",
    folder: str | None = None,
) -> dict:
    data: dict[str, str] = {}
    if folder is not None:
        data["folder"] = folder
    response = await client.post(
        "/api/pagebuilder/uploads",
        files={"file": (filename, PNG_BYTES, "image/png")},
        data=data,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_upload_happy_path(authed_client: AsyncClient) -> None:
    asset = await _upload(authed_client)
    assert asset["original_filename"] == "hero.png"
    assert asset["content_type"] == "image/png"
    assert asset["size_bytes"] > 0
    assert asset["url"].endswith(".png")


async def test_upload_rejects_unknown_content_type(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/pagebuilder/uploads",
        files={"file": ("malicious.html", b"<html></html>", "text/html")},
    )
    assert response.status_code == 415


async def test_upload_rejects_mime_mismatch(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/pagebuilder/uploads",
        files={"file": ("real.png", PNG_BYTES, "image/jpeg")},
    )
    assert response.status_code == 415


async def test_upload_rejects_oversize_file(authed_client, monkeypatch) -> None:
    # Shrink the byte cap so a tiny payload trips the 413.
    settings = authed_client._transport.app.state.pagebuilder.settings
    monkeypatch.setattr(settings, "media_max_bytes", 8)
    response = await authed_client.post(
        "/api/pagebuilder/uploads",
        files={"file": ("hero.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 413


async def test_list_uploads_after_upload(authed_client: AsyncClient) -> None:
    asset = await _upload(authed_client)
    response = await authed_client.get("/api/pagebuilder/uploads")
    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    assert len(items) == 1
    assert items[0]["id"] == asset["id"]
    assert items[0]["folder"] is None
    assert body["next_cursor"] is None
    assert body["folders"] == []


async def test_upload_with_folder(authed_client: AsyncClient) -> None:
    asset = await _upload(authed_client, folder="marketing/heros")
    assert asset["folder"] == "marketing/heros"
    body = (await authed_client.get("/api/pagebuilder/uploads")).json()
    assert "marketing/heros" in body["folders"]


async def test_upload_rejects_traversal_folder(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/api/pagebuilder/uploads",
        files={"file": ("hero.png", PNG_BYTES, "image/png")},
        data={"folder": "../etc"},
    )
    assert response.status_code == 422


async def test_upload_normalizes_folder(authed_client: AsyncClient) -> None:
    asset = await _upload(authed_client, folder="/news/2026/")
    assert asset["folder"] == "news/2026"


async def test_upload_empty_folder_is_unfiled(authed_client: AsyncClient) -> None:
    asset = await _upload(authed_client, folder="   ")
    assert asset["folder"] is None


async def test_list_uploads_search_filters_filename(authed_client: AsyncClient) -> None:
    await _upload(authed_client, filename="banner.png")
    await _upload(authed_client, filename="hero.png")
    body = (
        await authed_client.get("/api/pagebuilder/uploads", params={"search": "ban"})
    ).json()
    names = {item["original_filename"] for item in body["items"]}
    assert names == {"banner.png"}


async def test_list_uploads_filter_by_content_type(authed_client: AsyncClient) -> None:
    await _upload(authed_client, filename="hero.png")
    body = (
        await authed_client.get(
            "/api/pagebuilder/uploads", params={"content_type": "image/jpeg"}
        )
    ).json()
    assert body["items"] == []
    body = (
        await authed_client.get(
            "/api/pagebuilder/uploads", params={"content_type": "image/*"}
        )
    ).json()
    assert len(body["items"]) == 1


async def test_list_uploads_filter_by_folder(authed_client: AsyncClient) -> None:
    await _upload(authed_client, filename="a.png", folder="ads")
    await _upload(authed_client, filename="b.png", folder="news")
    await _upload(authed_client, filename="c.png")  # unfiled

    body = (
        await authed_client.get("/api/pagebuilder/uploads", params={"folder": "ads"})
    ).json()
    assert {item["original_filename"] for item in body["items"]} == {"a.png"}

    body = (
        await authed_client.get("/api/pagebuilder/uploads", params={"folder": ""})
    ).json()
    assert {item["original_filename"] for item in body["items"]} == {"c.png"}

    body = (await authed_client.get("/api/pagebuilder/uploads")).json()
    assert sorted(body["folders"]) == ["ads", "news"]


async def test_list_uploads_cursor_pagination(authed_client: AsyncClient) -> None:
    # 5 uploads, page size 2 → expect 3 pages: 2, 2, 1.
    ids: list[int] = []
    for i in range(5):
        ids.append((await _upload(authed_client, filename=f"f{i}.png"))["id"])

    first = (
        await authed_client.get("/api/pagebuilder/uploads", params={"limit": 2})
    ).json()
    assert [item["id"] for item in first["items"]] == [ids[4], ids[3]]
    assert first["next_cursor"] == ids[3]

    second = (
        await authed_client.get(
            "/api/pagebuilder/uploads",
            params={"limit": 2, "cursor": first["next_cursor"]},
        )
    ).json()
    assert [item["id"] for item in second["items"]] == [ids[2], ids[1]]
    assert second["next_cursor"] == ids[1]

    third = (
        await authed_client.get(
            "/api/pagebuilder/uploads",
            params={"limit": 2, "cursor": second["next_cursor"]},
        )
    ).json()
    assert [item["id"] for item in third["items"]] == [ids[0]]
    assert third["next_cursor"] is None


async def test_list_uploads_filter_by_size_range(authed_client: AsyncClient) -> None:
    asset = await _upload(authed_client)
    too_large = (
        await authed_client.get(
            "/api/pagebuilder/uploads",
            params={"min_size_bytes": asset["size_bytes"] + 1},
        )
    ).json()
    assert too_large["items"] == []

    in_range = (
        await authed_client.get(
            "/api/pagebuilder/uploads",
            params={
                "min_size_bytes": 0,
                "max_size_bytes": asset["size_bytes"],
            },
        )
    ).json()
    assert len(in_range["items"]) == 1


async def test_delete_upload(authed_client: AsyncClient) -> None:
    asset = await _upload(authed_client)
    response = await authed_client.delete(f"/api/pagebuilder/uploads/{asset['id']}")
    assert response.status_code == 204
    items = (await authed_client.get("/api/pagebuilder/uploads")).json()["items"]
    assert items == []


async def test_delete_unknown_upload_returns_404(authed_client: AsyncClient) -> None:
    response = await authed_client.delete("/api/pagebuilder/uploads/9999")
    assert response.status_code == 404
