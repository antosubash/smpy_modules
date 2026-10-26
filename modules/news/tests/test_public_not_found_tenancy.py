"""The site 404 on a multi-tenant host (#248).

A request that resolved no tenant gets the page with no layout and runs no
lookup — never the default tenant's site. One tenant's article, asked for at
another tenant's address, is that tenant's ordinary 404 in its own frame.
"""

from __future__ import annotations

import pytest
from factories import make_article
from httpx import AsyncClient
from pagebuilder.layout_service import LayoutService
from simple_module_db import tenant_context
from site_app import COMPONENT, FOOTER, HEADER, INERTIA, set_layout, site_client
from tenant_app import as_tenant

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]

A, B = as_tenant("acme"), as_tenant("globex")
OTHER = {"content": [{"type": "Heading", "props": {"id": "g", "text": "Globex"}}]}


@pytest.fixture
async def site():
    async for client in site_client(multi=True):
        yield client


async def _seed(client: AsyncClient) -> None:
    await set_layout(client, "acme")
    await set_layout(client, "globex", header=OTHER, footer=OTHER)
    with tenant_context("acme"):
        async with client.db_state.session_factory() as db:  # type: ignore[attr-defined]
            await make_article(db, slug="hello", title="Hello A")


@pytest.mark.parametrize("path", ["/news/hello", "/news/", "/news/tag/x", "/news/category/x"])
async def test_no_tenant_gets_the_page_without_any_layout(
    site: AsyncClient, monkeypatch, path: str
) -> None:
    await _seed(site)
    calls: list[object] = []

    async def spy(self):  # pragma: no cover - must not run
        calls.append(self)
        raise AssertionError("read a layout with no tenant")

    monkeypatch.setattr(LayoutService, "get", spy)
    response = await site.get(path, headers=INERTIA)
    assert response.status_code == 404, response.text
    page = response.json()
    assert page["component"] == COMPONENT
    assert page["props"]["layout_header"] is None
    assert page["props"]["layout_footer"] is None
    assert page["props"]["site_nav"] is None
    assert response.headers["Cache-Control"] == "no-store"
    assert calls == []


async def test_no_tenant_json_is_the_unknown_slug_answer(site: AsyncClient) -> None:
    response = await site.get("/news/hello", headers={"Accept": "application/json"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Article not found"}


async def test_each_tenant_sees_its_own_article_or_its_own_404(site: AsyncClient) -> None:
    await _seed(site)
    assert (await site.get("/news/hello", headers={**INERTIA, **A})).status_code == 200
    missing = await site.get("/news/hello", headers={**INERTIA, **B})
    assert missing.status_code == 404
    props = missing.json()["props"]
    # Globex's frame, never Acme's: the article's tenant leaks nothing.
    assert props["layout_header"] == OTHER
    assert props["layout_footer"] == OTHER
    assert HEADER != OTHER and FOOTER != OTHER
    # Keyed on whatever picks the tenant, and never kept.
    assert "Cookie" in missing.headers["Vary"]
    assert missing.headers["Cache-Control"] == "no-store"
    # Globex's 404 for Acme's slug is the same as for a slug nobody has.
    nobody = await site.get("/news/never-existed", headers={**INERTIA, **B})
    assert nobody.json()["props"] == props
