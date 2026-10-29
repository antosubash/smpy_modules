"""The prompt route tests' fixture (``prompts_world``) and helpers."""

from __future__ import annotations

import pytest_asyncio
from sm_images.models import Visibility
from sm_images.module import ImagesModule
from sm_images.pipeline import registry

from tests.access_support import EDITOR, OWNER, VIEWER, collection, headers, image
from tests.access_support import share as make_share
from tests.pipeline_support import use_steps

BASE = "/api/images"


@pytest_asyncio.fixture
async def prompts_world(client, storage):
    """olga's private collection with one stored image, an edit share for eddie
    and a view share for vic; the eager web runtime."""
    from sm_images.storage import ImageStore

    from tests.pipeline_support import jpeg

    use_steps()
    ImagesModule._use_runtime(client.app, client.db_state.session_factory)
    coll = collection("prompts", Visibility.PRIVATE, OWNER)
    async with client.db_state.session_factory() as s:
        s.add(coll)
        await s.flush()
        pic = image(coll, "a.jpg")
        s.add_all([pic, make_share(coll, EDITOR, "edit"), make_share(coll, VIEWER, "view")])
        await s.commit()
    data = jpeg()
    await ImageStore(storage).put(pic.storage_key, data, content_type="image/jpeg", size=len(data))
    yield type("W", (), {"cid": str(coll.id), "iid": str(pic.id), "c": client})
    registry.reset_registry()


async def create_prompt(world, who=OWNER, **body):
    body = {"name": "count", "instruction": "Count the cows.", **body}
    return await world.c.post(
        f"{BASE}/collections/{world.cid}/prompts", json=body, headers=headers(who)
    )
