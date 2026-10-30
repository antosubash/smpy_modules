"""``…/display`` of an original a browser cannot draw (HEIC, HEIF, TIFF).

Without a display copy the display route serves the original, which for those
types is bytes no browser renders: the viewer showed a broken image. It serves
the widest rendition cut from the current bytes instead, and the original only
when there is none.
"""

from __future__ import annotations

import pytest_asyncio
from sm_images.models import Image, Rendition
from sm_images.storage import ImageStore
from sm_images.storage import keys as storage_keys
from sqlalchemy import delete, update

from tests.support.access import OWNER, headers
from tests.support.serve import blob, seed_gallery


@pytest_asyncio.fixture
async def g(client, storage):
    return await seed_gallery(client.db_state.session_factory, storage)


async def _as_heic(client, storage, g, *, large: bool = False, bare: bool = False) -> bytes | None:
    image_id = g.ids["priv.plain"]
    data = None
    async with client.db_state.session_factory() as s:
        await s.execute(update(Image).where(Image.id == image_id).values(content_type="image/heic"))
        if large:
            key = storage_keys.rendition_key("default", "c", str(image_id), "large", 0, "a1")
            data = blob("priv.plain.large")
            await ImageStore(storage).put(key, data, content_type="image/jpeg", size=len(data))
            s.add(
                Rendition(
                    image_id=image_id,
                    size="large",
                    storage_key=key,
                    width=1600,
                    height=1200,
                    source_generation=0,
                )
            )
        if bare:
            await s.execute(delete(Rendition).where(Rendition.image_id == image_id))
        await s.commit()
    return data


async def test_a_heic_original_displays_as_its_widest_rendition(client, storage, g):
    large = await _as_heic(client, storage, g, large=True)
    got = await client.get(g.url("priv", "plain", "display"), headers=headers(OWNER))
    assert got.status_code == 200, got.text
    assert got.content == large
    assert got.headers["content-type"] == "image/jpeg"


async def test_the_only_rendition_is_the_widest_one(client, storage, g):
    await _as_heic(client, storage, g)
    got = await client.get(g.url("priv", "plain", "display"), headers=headers(OWNER))
    assert got.content == g.bytes["priv.plain.small"]


async def test_without_a_rendition_the_original_is_still_served(client, storage, g):
    await _as_heic(client, storage, g, bare=True)
    got = await client.get(g.url("priv", "plain", "display"), headers=headers(OWNER))
    assert got.content == g.bytes["priv.plain.original"]
    assert got.headers["content-type"] == "image/heic"


async def test_a_jpeg_original_is_served_as_it_is(client, g):
    got = await client.get(g.url("priv", "plain", "display"), headers=headers(OWNER))
    assert got.content == g.bytes["priv.plain.original"]
