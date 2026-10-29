"""The viewer's previous and next image, in gallery order (QA TEST-006h).

``neighbors`` names the image before and after this one in the gallery's own
order (newest first). A viewer's neighbours are only images they may open: a
withheld image is never one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sm_images.models import Collection, Image
from sm_images.services.neighbors import neighbors
from sqlalchemy import update

from tests.test_console_views import INERTIA, VIEWS, props
from tests.upload_support import OLGA, jpeg, make_collection, post_files


async def _three(client) -> tuple[str, list[str]]:
    cid = await make_collection(client, OLGA)
    ids = []
    for n in range(3):
        got = await post_files(
            client, cid, [(f"{n}.jpg", jpeg(color=("blue", "red", "green")[n]), "image/jpeg")]
        )
        ids.append(got.json()["results"][0]["id"])
    base = datetime(2026, 1, 1, tzinfo=UTC)
    async with client.db_state.session_factory() as s:  # oldest first: 0, 1, 2
        for n, iid in enumerate(ids):
            await s.execute(
                update(Image)
                .where(Image.id == uuid.UUID(iid))
                .values(created_at=base + timedelta(minutes=n))
            )
        await s.commit()
    return cid, ids


async def test_the_viewer_page_names_its_neighbours_in_gallery_order(uploads):
    _, ids = await _three(uploads)
    page = props(await uploads.get(f"{VIEWS}/images/{ids[1]}", headers={**OLGA, **INERTIA}))
    assert page["neighbors"] == {"prev": ids[2], "next": ids[0]}  # newest first
    first = props(await uploads.get(f"{VIEWS}/images/{ids[2]}", headers={**OLGA, **INERTIA}))
    assert first["neighbors"] == {"prev": None, "next": ids[1]}


async def test_a_withheld_image_is_never_a_viewers_neighbour(uploads):
    cid, ids = await _three(uploads)
    async with uploads.db_state.session_factory() as s:
        coll = await s.get(Collection, uuid.UUID(cid))
        image = await s.get(Image, uuid.UUID(ids[1]))
        assert await neighbors(s, coll, image, gated=False) == {"prev": ids[2], "next": ids[0]}
        coll.protect_originals = True  # nothing redacted: every image is withheld
        gated = await neighbors(s, coll, image, gated=True)
        assert gated == {"prev": None, "next": None}
