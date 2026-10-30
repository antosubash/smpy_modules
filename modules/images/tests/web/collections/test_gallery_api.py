"""The gallery list and ``/images/{id}``: filters, cursor, manual location, soft delete."""

from __future__ import annotations

import json
import uuid

from sm_images.models import Collection, Group, LocationSource, StepRun, StepStatus
from sqlalchemy import update

from tests.support.access import share
from tests.support.stub_auth import as_user
from tests.support.upload import BASE, OLGA, all_rows, jpeg, make_collection, post_files

IMAGES = "/api/images/images"


async def seed(client) -> tuple[str, dict[str, str]]:
    cid = await make_collection(client)
    meta = {"a.jpg": {"lat": 10, "lng": 20, "group_key": "G"}, "b.jpg": {}, "c.jpg": {}}
    files = [
        (n, jpeg(color=c), "image/jpeg")
        for n, c in zip(meta, ("red", "blue", "green"), strict=True)
    ]
    got = await post_files(client, cid, files, metadata=json.dumps(meta))
    assert got.status_code == 200, got.text
    return cid, {r["filename"]: r["id"] for r in got.json()["results"]}


async def names(client, cid, **params) -> list[str]:
    got = await client.get(f"{BASE}/{cid}/images", params=params, headers=OLGA)
    assert got.status_code == 200, got.text
    return sorted(i["filename"] for i in got.json()["items"])


async def test_list_filters(uploads):
    cid, ids = await seed(uploads)
    assert await names(uploads, cid) == ["a.jpg", "b.jpg", "c.jpg"]
    assert await names(uploads, cid, has_location="true") == ["a.jpg"]
    assert await names(uploads, cid, has_location="false") == ["b.jpg", "c.jpg"]
    (group,) = await all_rows(uploads, Group)
    assert await names(uploads, cid, group=str(group.id)) == ["a.jpg"]
    async with uploads.db_state.session_factory() as s:
        # Ingest already planned the default pipeline's runs; set their states.
        await s.execute(update(StepRun).values(status=StepStatus.COMPLETED))
        for name, status in (("b.jpg", StepStatus.FAILED), ("c.jpg", StepStatus.PENDING)):
            await s.execute(
                update(StepRun)
                .where(StepRun.image_id == uuid.UUID(ids[name]), StepRun.step == "exif")
                .values(status=status)
            )
        await s.commit()
    assert await names(uploads, cid, step="exif") == ["a.jpg", "b.jpg", "c.jpg"]
    assert await names(uploads, cid, step="exif", step_status="failed") == ["b.jpg"]
    assert await names(uploads, cid, step_status="pending") == ["c.jpg"]
    assert await names(uploads, cid, review_status="accepted") == []


async def test_cursor_pages_cover_everything_once(uploads):
    cid, ids = await seed(uploads)
    seen, cursor, total = [], None, None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = (await uploads.get(f"{BASE}/{cid}/images", params=params, headers=OLGA)).json()
        total = page["total"] if total is None else total
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert sorted(seen) == sorted(ids.values()) and total == 3
    bad = await uploads.get(f"{BASE}/{cid}/images", params={"cursor": "%%%"}, headers=OLGA)
    assert bad.status_code == 422


async def test_detail_and_patch_manual_location(uploads):
    cid, ids = await seed(uploads)
    url = f"{IMAGES}/{ids['b.jpg']}"
    got = await uploads.get(url, headers=OLGA)
    assert got.status_code == 200 and got.json()["collection_id"] == cid
    assert got.json()["has_display"] is False

    moved = await uploads.patch(url, json={"lat": -5, "lng": 30}, headers=OLGA)
    assert moved.status_code == 200, moved.text
    assert (moved.json()["lat"], moved.json()["location_source"]) == (-5, "manual")
    (coll,) = await all_rows(uploads, Collection)
    assert (coll.located_count, coll.bbox_miny, coll.bbox_maxx) == (2, -5.0, 30.0)

    cleared = await uploads.patch(url, json={"lat": None, "lng": None}, headers=OLGA)
    assert cleared.json()["location_source"] is None
    (coll,) = await all_rows(uploads, Collection)
    assert (coll.located_count, coll.bbox_miny, coll.bbox_maxx) == (1, 10.0, 20.0)  # recomputed

    lone = await uploads.patch(url, json={"lat": 1, "lng": None}, headers=OLGA)
    assert lone.status_code == 422


async def test_patch_is_a_compare_and_set(uploads, monkeypatch):
    """A location written between our read and our write is not overwritten."""
    from sm_images.web.services import gallery

    _, ids = await seed(uploads)
    real_get = gallery.get

    async def racing_get(db, collection, image_id):
        row = await real_get(db, collection, image_id)
        async with uploads.db_state.session_factory() as other:
            await other.execute(
                update(type(row))
                .where(type(row).id == image_id)
                .values(lat=1.0, lng=1.0, location_source=LocationSource.EXIF)
            )
            await other.commit()
        return row

    monkeypatch.setattr(gallery, "get", racing_get)
    got = await uploads.patch(f"{IMAGES}/{ids['c.jpg']}", json={"lat": 2, "lng": 2}, headers=OLGA)
    assert got.status_code == 409, got.text


async def test_delete_is_owner_or_manage_and_soft(uploads):
    cid, ids = await seed(uploads)
    async with uploads.db_state.session_factory() as s:
        s.add(share(await s.get(Collection, uuid.UUID(cid)), "eddie", "edit"))
        await s.commit()
    editor = as_user("eddie", ("images.view",))
    url = f"{IMAGES}/{ids['a.jpg']}"
    assert (await uploads.patch(url, json={"lat": 1, "lng": 1}, headers=editor)).status_code == 200
    assert (await uploads.delete(url, headers=editor)).status_code == 403
    assert (await uploads.delete(url, headers=OLGA)).status_code == 204
    assert (await uploads.get(url, headers=OLGA)).status_code == 404
    trashed = [r for r in await all_rows(uploads, include_deleted=True) if r.is_deleted]
    assert [str(r.id) for r in trashed] == [ids["a.jpg"]]
    (coll,) = await all_rows(uploads, Collection)
    assert (coll.image_count, coll.located_count) == (2, 0)
