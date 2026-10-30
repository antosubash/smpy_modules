"""The console's collection page knows its public page's path (QA TEST-017)."""

from __future__ import annotations

from tests.collections.test_console_views import INERTIA, VIEWS, props
from tests.support.upload import BASE, OLGA, make_collection


async def test_the_collection_page_carries_its_public_path(uploads):
    cid = await make_collection(uploads, OLGA)
    slug = (await uploads.get(f"{BASE}/{cid}", headers=OLGA)).json()["slug"]
    page = props(await uploads.get(f"{VIEWS}/{cid}", headers={**OLGA, **INERTIA}))
    assert page["public_path"] == f"/images/c/{slug}"
