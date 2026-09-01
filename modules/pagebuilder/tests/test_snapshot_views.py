from __future__ import annotations

import pytest
from conftest import create_draft

pytestmark = pytest.mark.asyncio

_INERTIA = {"X-Inertia": "true"}


async def test_content_view_renders_the_snapshot_list(authed_client):
    await create_draft(authed_client, slug="home", title="Home")
    await authed_client.post("/api/pagebuilder/snapshots", json={"note": "first"})

    response = await authed_client.get("/pagebuilder/content", headers=_INERTIA)
    assert response.status_code == 200
    body = response.json()
    assert body["component"] == "PageBuilder/ContentSnapshots"
    assert [s["note"] for s in body["props"]["snapshots"]] == ["first"]
    assert body["props"]["pending"] is None


async def test_content_view_surfaces_a_pending_import(authed_client):
    created = await authed_client.post("/api/pagebuilder/snapshots", json={})
    await authed_client.post(
        f"/api/pagebuilder/snapshots/{created.json()['id']}/restore"
    )

    response = await authed_client.get("/pagebuilder/content", headers=_INERTIA)
    assert response.json()["props"]["pending"]["status"] == "pending"


async def test_review_view_renders_the_plan(authed_client):
    await create_draft(authed_client, slug="home", title="Home")
    created = await authed_client.post("/api/pagebuilder/snapshots", json={})
    await authed_client.post(
        f"/api/pagebuilder/snapshots/{created.json()['id']}/restore"
    )

    response = await authed_client.get("/pagebuilder/content/review", headers=_INERTIA)
    assert response.status_code == 200
    body = response.json()
    assert body["component"] == "PageBuilder/ContentImportReview"
    assert body["props"]["pending"]["plan"]["pages"]["unchanged"][0]["slug"] == "home"


async def test_review_view_is_reachable_with_nothing_staged(authed_client):
    response = await authed_client.get("/pagebuilder/content/review", headers=_INERTIA)
    assert response.status_code == 200
    assert response.json()["props"]["pending"] is None


async def test_content_route_does_not_shadow_the_page_editor(authed_client):
    """`/content` is a literal segment, `/{page_id}/edit` a parameterised one."""
    page = await create_draft(authed_client, slug="home", title="Home")
    response = await authed_client.get(
        f"/pagebuilder/{page['id']}/edit", headers=_INERTIA
    )
    assert response.json()["component"] == "PageBuilder/PageEditor"


async def test_menu_lists_import_export():
    # async only to match the module-level asyncio mark; nothing here awaits.
    from pagebuilder.module import PagebuilderModule
    from simple_module_core.menu import MenuRegistry

    registry = MenuRegistry()
    PagebuilderModule().register_menu_items(registry)
    items = {item.label: item for item in registry.all_items}
    assert "Import / Export" in items
    assert items["Import / Export"].url == "/pagebuilder/content"
    # After Media library (220), so the group reads in workflow order.
    assert items["Import / Export"].order == 230
