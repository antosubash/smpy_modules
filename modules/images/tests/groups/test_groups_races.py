"""The role-only PATCH race and the counts a regroup reports (Task 21 fix round 1)."""

from __future__ import annotations

import uuid

import pytest
from sm_images.models import Group, Image
from sm_images.module import ImagesModule
from sm_images.pipeline.runtime import current_runtime
from sm_images.services import regroup_write as write
from sqlalchemy import update

from tests.groups.test_groups import IMAGES, OLGA, make_group, put, seed
from tests.support.read_routes import READ_ROUTES


@pytest.fixture
def web_runtime(uploads):
    ImagesModule._use_runtime(uploads.app, uploads.db_state.session_factory)


def _rt(_client=None):
    runtime = current_runtime()
    assert runtime is not None
    return runtime


async def test_role_only_patch_cannot_revert_a_concurrent_group_change(uploads, monkeypatch):
    cid, ids = await seed(uploads, ["a"])
    one, two = await make_group(uploads, cid, "one"), await make_group(uploads, cid, "two")
    await put(uploads, ids["a"], group_id=one, group_role="north")
    from sm_images.services import gallery

    real = gallery.get

    async def racing(db, collection, image_id):
        row = await real(db, collection, image_id)
        async with uploads.db_state.session_factory() as other:
            await other.execute(
                update(Image).where(Image.id == image_id).values(group_id=uuid.UUID(two))
            )
            await other.commit()
        return row

    monkeypatch.setattr(gallery, "get", racing)
    got = await put(uploads, ids["a"], group_role="east")
    assert got.status_code == 409 and got.json()["code"] == "conflict"
    monkeypatch.setattr(gallery, "get", real)
    now = await uploads.get(f"{IMAGES}/{ids['a']}", headers=OLGA)
    assert (now.json()["group_id"], now.json()["group_role"]) == (two, "north")


async def test_a_role_without_a_group_has_its_own_code(uploads):
    _, ids = await seed(uploads, ["a"])
    got = await put(uploads, ids["a"], group_role="east")
    assert got.status_code == 422 and got.json()["code"] == "role_needs_group"


async def test_ensure_groups_tells_a_competing_insert_from_its_own(
    uploads, web_runtime, monkeypatch
):
    cid, _ = await seed(uploads, [])
    rt = _rt(uploads)
    async with rt.session_factory() as db:
        rival = Group(collection_id=uuid.UUID(cid), key="rival")
        db.add(rival)
        await db.commit()
    real = write.keys_to_ids
    calls = {"n": 0}

    async def blind_first_time(db, collection_id, keys):
        calls["n"] += 1
        return {} if calls["n"] == 1 else await real(db, collection_id, keys)

    monkeypatch.setattr(write, "keys_to_ids", blind_first_time)
    async with rt.session_factory() as db:
        ids, created, existing = await write.ensure_groups(
            db, "default", uuid.UUID(cid), ["mine", "rival"]
        )
        await db.commit()
    assert (created, len(existing)) == (1, 1) and set(ids) == {"mine", "rival"}
    assert ids["mine"] != ids["rival"]
    assert ids["rival"] == rival.id


async def test_assigned_counts_only_rows_that_changed(uploads, web_runtime):
    cid, ids = await seed(uploads, ["s1_point.jpg", "s2_point.jpg"])
    rt = _rt(uploads)
    manual = await make_group(uploads, cid, "manual")
    async with rt.session_factory() as db:
        coll_id = uuid.UUID(cid)
        groups, _, _ = await write.ensure_groups(db, "default", coll_id, ["s1", "s2"])
        # between planning and writing, a manual assignment takes one of the two
        await db.execute(
            update(Image)
            .where(Image.id == uuid.UUID(ids["s1_point.jpg"]))
            .values(group_id=uuid.UUID(manual))
        )
        changes = [
            (uuid.UUID(ids["s1_point.jpg"]), "s1", "point"),
            (uuid.UUID(ids["s2_point.jpg"]), "s2", "point"),
        ]
        assert await write.apply_chunk(db, coll_id, changes, groups, False) == 1
        await db.commit()


def test_group_paths_are_listed_for_the_leak_test():
    assert "/api/images/regroups/{regroup_id}" in {r.path for r in READ_ROUTES}
