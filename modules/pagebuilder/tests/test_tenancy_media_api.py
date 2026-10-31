"""Admin media endpoints between two live tenants (#130).

``test_tenancy_media`` covers the storage layout and the static mount; this
covers the API on top of it — the listing, the detail screen, edits and both
deletes — the way ``test_tenancy_isolation`` does for pages.
"""

from __future__ import annotations

import io

import pytest
from httpx import AsyncClient
from PIL import Image
from tenant_app import as_tenant, create_page, multi_client

API = "/api/pagebuilder/uploads"
A, B = as_tenant("acme"), as_tenant("globex")

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
async def mt(tmp_path):
    async for client in multi_client(tmp_path):
        yield client


async def _upload(client: AsyncClient, headers, name: str = "secret.png") -> dict:
    response = await client.post(
        API, files={"file": (name, _png(), "image/png")}, data={"folder": "private"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_an_upload_is_invisible_to_the_other_tenant(mt: AsyncClient) -> None:
    asset = await _upload(mt, A)

    assert (await mt.get(f"{API}/{asset['id']}", headers=A)).status_code == 200
    assert (await mt.get(f"{API}/{asset['id']}", headers=B)).status_code == 404
    listed = await mt.get(API, headers=B)
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    searched = await mt.get(API, params={"search": "secret"}, headers=B)
    assert searched.json()["items"] == []
    mine = await mt.get(API, params={"search": "secret"}, headers=A)
    assert [i["id"] for i in mine.json()["items"]] == [asset["id"]]


async def test_the_other_tenant_cannot_change_or_delete_it(mt: AsyncClient) -> None:
    asset = await _upload(mt, A)
    url = f"{API}/{asset['id']}"

    assert (await mt.put(url, json={"alt_text": "pwned"}, headers=B)).status_code == 404
    assert (await mt.delete(f"{url}/checked", headers=B)).status_code == 404
    assert (await mt.delete(url, headers=B)).status_code == 404

    kept = await mt.get(url, headers=A)
    assert kept.status_code == 200
    assert kept.json()["asset"]["alt_text"] == ""


async def test_the_file_is_served_only_in_its_own_tenant(mt: AsyncClient) -> None:
    asset = await _upload(mt, A)

    assert (await mt.get(asset["url"], headers=A)).status_code == 200
    assert (await mt.get(asset["url"], headers=B)).status_code == 404
    # The flat legacy form of the same name resolves inside B's own directory.
    flat = asset["url"].replace("/acme/", "/")
    assert (await mt.get(flat, headers=B)).status_code == 404


async def test_same_filename_uploads_are_two_assets(mt: AsyncClient) -> None:
    a = await _upload(mt, A, "logo.png")
    b = await _upload(mt, B, "logo.png")

    assert a["id"] != b["id"]
    assert a["url"] != b["url"]
    assert [i["id"] for i in (await mt.get(API, headers=B)).json()["items"]] == [b["id"]]


async def test_usage_counts_only_the_assets_own_tenant(mt: AsyncClient) -> None:
    """B pasting A's URL into a page must not show up — or block a checked
    delete — on A's detail screen: that would leak B's page titles to A."""
    asset = await _upload(mt, A)
    body = {"content": [{"type": "Image", "props": {"src": asset["url"]}}]}
    await create_page(mt, B, "borrower", "B's page", draft_data=body)

    detail = (await mt.get(f"{API}/{asset['id']}", headers=A)).json()

    assert detail["used_in"] == []
    assert detail["used_in_total"] == 0
    assert (await mt.delete(f"{API}/{asset['id']}/checked", headers=A)).status_code == 204


async def test_usage_still_finds_the_tenants_own_pages(mt: AsyncClient) -> None:
    """The control for the test above: usage is not simply always empty."""
    asset = await _upload(mt, A)
    body = {"content": [{"type": "Image", "props": {"src": asset["url"]}}]}
    await create_page(mt, A, "user", "A's page", draft_data=body)
    await create_page(mt, B, "borrower", "B's page", draft_data=body)

    detail = (await mt.get(f"{API}/{asset['id']}", headers=A)).json()

    assert [u["title"] for u in detail["used_in"]] == ["A's page"]
    assert detail["used_in_total"] == 1
