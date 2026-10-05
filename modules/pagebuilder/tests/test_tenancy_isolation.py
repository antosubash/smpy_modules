"""Admin-side isolation between two live tenants (#38)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from tenant_app import as_tenant, multi_client

API = "/api/pagebuilder/pages"
A, B = as_tenant("acme"), as_tenant("globex")

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]


@pytest.fixture
async def mt(tmp_path):
    async for client in multi_client(tmp_path):
        yield client


async def _create(client: AsyncClient, headers, slug="about", title="About", **extra) -> dict:
    response = await client.post(
        API,
        json={"title": title, "slug": slug, "draft_data": {"content": []}, **extra},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_page_is_invisible_to_the_other_tenant(mt: AsyncClient) -> None:
    page = await _create(mt, A, slug="secret")
    url = f"{API}/{page['id']}"
    assert (await mt.get(url, headers=A)).status_code == 200
    assert (await mt.get(url, headers=B)).status_code == 404
    listed = await mt.get(API, headers=B)
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    assert [p["slug"] for p in (await mt.get(API, headers=A)).json()["items"]] == ["secret"]


async def test_the_other_tenant_cannot_change_or_delete_it(mt: AsyncClient) -> None:
    page = await _create(mt, A, slug="secret", title="Mine")
    url = f"{API}/{page['id']}"
    assert (await mt.put(url, json={"title": "Hacked"}, headers=B)).status_code == 404
    assert (await mt.post(f"{url}/publish", json={}, headers=B)).status_code == 404
    assert (await mt.delete(url, headers=B)).status_code == 404
    kept = await mt.get(url, headers=A)
    assert kept.status_code == 200
    assert kept.json()["title"] == "Mine"


async def test_same_locale_and_slug_in_both_tenants(mt: AsyncClient) -> None:
    a = await _create(mt, A, slug="about", title="A about")
    b = await _create(mt, B, slug="about", title="B about")
    assert a["id"] != b["id"]
    # ...but not twice in one tenant.
    again = await mt.post(
        API, json={"title": "x", "slug": "about", "draft_data": {}}, headers=A
    )
    assert again.status_code == 409


async def test_same_redirect_source_in_both_tenants(mt: AsyncClient) -> None:
    ids = {}
    for name, headers in (("a", A), ("b", B)):
        page = await _create(mt, headers, slug="old", title=name)
        await mt.post(f"{API}/{page['id']}/publish", json={}, headers=headers)
        renamed = await mt.put(f"{API}/{page['id']}", json={"slug": "new"}, headers=headers)
        assert renamed.status_code == 200, renamed.text
        ids[name] = page["id"]
    # Both tenants now hold a redirect from "old"; each can recycle the slug.
    for headers in (A, B):
        await _create(mt, headers, slug="old", title="reused")


async def test_each_tenant_gets_its_own_layout(mt: AsyncClient) -> None:
    url = "/api/pagebuilder/layout"
    header_a = {"content": [{"type": "Text", "props": {"id": "a"}}], "root": {"props": {}}}
    put = await mt.put(url, json={"header_data": header_a}, headers=A)
    assert put.status_code == 200, put.text
    a = (await mt.get(url, headers=A)).json()
    b = (await mt.get(url, headers=B)).json()
    assert a["header_data"] == header_a
    assert b["header_data"] != header_a
    assert a["id"] != b["id"]
    # Editing B's layout leaves A's alone.
    header_b = {"content": [], "root": {"props": {"title": "B"}}}
    assert (await mt.put(url, json={"header_data": header_b}, headers=B)).status_code == 200
    assert (await mt.get(url, headers=A)).json()["header_data"] == header_a
    assert (await mt.get(url, headers=B)).json()["header_data"] == header_b


async def test_admin_without_a_tenant_is_403(mt: AsyncClient) -> None:
    assert (await mt.get(API)).status_code == 403
