"""The public collection page and its image list (Task 27).

``/images/c/{slug}`` is an Inertia screen for anyone; ``…/public/c/{slug}/images``
is the JSON list the screen and the pagebuilder block read. Only a public
collection answers; a private one is the 404 an unknown slug gets.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sm_images.models import Image
from sm_images.tenancy import DEFAULT_TENANT, tenant_scope
from sqlalchemy import update

from tests.access_support import OWNER, headers
from tests.serve_support import seed_gallery


@pytest_asyncio.fixture
async def g(client, storage):
    return await seed_gallery(client.db_state.session_factory, storage)


def _list(slug: str, query: str = "") -> str:
    return f"/api/images/public/c/{slug}/images{query}"


async def test_public_list_has_public_urls_and_no_filenames(client, g):
    got = await client.get(_list(g.slugs["pub"]))
    assert got.status_code == 200, got.text
    body = got.json()
    by_id = {i["id"]: i for i in body["items"]}
    assert set(by_id) == {str(g.ids["pub.plain"]), str(g.ids["pub.blurred"])}
    blurred = by_id[str(g.ids["pub.blurred"])]
    assert blurred["thumb_url"] == g.public_url("pub", "blurred", "r/small")
    assert blurred["display_url"] == g.public_url("pub", "blurred", "display")
    assert "pub.blurred.jpg" not in got.text


async def test_public_list_pages_by_cursor(client, g):
    first = (await client.get(_list(g.slugs["pub"], "?limit=1"))).json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    again = await client.get(_list(g.slugs["pub"], f"?limit=1&cursor={first['next_cursor']}"))
    second = again.json()
    assert len(second["items"]) == 1
    assert second["items"][0]["id"] != first["items"][0]["id"]
    assert second["next_cursor"] is None


async def test_public_list_skips_an_image_without_a_current_small_rendition(client, g):
    async with client.db_state.session_factory() as s:
        with tenant_scope(DEFAULT_TENANT):
            await s.execute(
                update(Image)
                .where(Image.id == g.ids["pub.blurred"])
                .values(display_generation=5)
                .execution_options(synchronize_session=False)
            )
            await s.commit()
    body = (await client.get(_list(g.slugs["pub"]))).json()
    assert [i["id"] for i in body["items"]] == [str(g.ids["pub.plain"])]


@pytest.mark.parametrize("who", [None, OWNER])
async def test_private_collection_list_is_404(client, g, who):
    got = await client.get(_list(g.slugs["priv"]), headers=headers(who))
    assert got.status_code == 404
    assert got.headers["cache-control"] == "no-store"


async def test_page_is_served_anonymously_with_safe_props(client, g):
    got = await client.get(f"/images/c/{g.slugs['pub']}", headers={"X-Inertia": "true"})
    assert got.status_code == 200, got.text
    page = got.json()
    assert page["component"] == "Images/PublicCollection"
    shown = page["props"]["collection"]
    assert shown["slug"] == g.slugs["pub"]
    assert set(shown) == {"slug", "name", "description", "image_count", "located_count", "bbox"}
    assert page["props"]["map_style_url"] == "https://tiles.openfreemap.org/styles/positron"
    assert got.headers["cache-control"] == "private, no-cache"


@pytest.mark.parametrize("slug", ["priv", None])
async def test_page_for_private_or_unknown_is_404(client, g, slug):
    got = await client.get(f"/images/c/{g.slugs[slug] if slug else 'nope'}")
    assert got.status_code == 404


def test_mount_public_pages_is_idempotent():
    """A lifespan restart (tests, dev reload) runs ``on_startup`` again on the
    same app; the page must not be registered twice."""
    from fastapi import FastAPI
    from fastapi.routing import iter_route_contexts
    from sm_images.module import ImagesModule

    app = FastAPI()
    ImagesModule.mount_public_pages(app)
    ImagesModule.mount_public_pages(app)
    paths = [r.path for r in iter_route_contexts(app.routes) if r.path]
    assert paths.count("/images/c/{slug}") == 1
