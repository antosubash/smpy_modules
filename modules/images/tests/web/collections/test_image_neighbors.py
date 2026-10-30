"""The viewer's previous and next image, in gallery order (QA TEST-006h).

``neighbors`` names the image before and after this one in the gallery's own
order (newest first). A viewer's neighbours are only images they may open: a
withheld image is never one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_images.models import Collection, Image
from sm_images.web.services.neighbors import neighbors
from sqlalchemy import update

from tests.support.upload import OLGA, jpeg, make_collection, post_files
from tests.web.collections.test_console_views import INERTIA, VIEWS, props


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


async def test_ties_on_created_at_are_ordered_by_id(uploads):
    cid, ids = await _three(uploads)
    same = datetime(2026, 2, 1, tzinfo=UTC)
    async with uploads.db_state.session_factory() as s:
        await s.execute(
            update(Image).where(Image.collection_id == uuid.UUID(cid)).values(created_at=same)
        )
        await s.commit()
        coll = await s.get(Collection, uuid.UUID(cid))
        order = sorted(ids, key=uuid.UUID, reverse=True)  # gallery order on a tie: id desc
        middle = await s.get(Image, uuid.UUID(order[1]))
        found = await neighbors(s, coll, middle, gated=False)
    assert found == {"prev": order[0], "next": order[2]}


async def test_each_side_is_one_index_seek(uploads):
    """Review: an OR of the two halves defeats the (collection_id, created_at,
    id) index; a row-value comparison seeks it."""
    from sm_images.web.services.neighbors import side_statements

    cid, ids = await _three(uploads)
    async with uploads.db_state.session_factory() as s:
        if s.bind.dialect.name != "sqlite":
            pytest.skip("the plan is checked on SQLite")
        coll = await s.get(Collection, uuid.UUID(cid))
        image = await s.get(Image, uuid.UUID(ids[1]))
        conn = await s.connection()
        for stmt in side_statements(coll, image, gated=False):
            sql = str(stmt.compile(s.bind, compile_kwargs={"literal_binds": True}))
            rows = await conn.exec_driver_sql(f"EXPLAIN QUERY PLAN {sql}")
            plan = " ".join(str(r[-1]) for r in rows.all())
            assert "ix_images_image_gallery" in plan, plan
            assert "(created_at,id)" in plan.replace(" ", ""), plan
            assert "TEMP B-TREE" not in plan, plan
