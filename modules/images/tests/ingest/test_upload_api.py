"""Multipart batch upload: limits, metadata, per-file isolation, what a row gets."""

from __future__ import annotations

import json
import uuid

from sm_images import constants
from sm_images.contracts.events import ImageAdded
from sm_images.models import Collection, Group, LocationSource
from sqlalchemy import select

from tests.support.access import share
from tests.support.stub_auth import as_user
from tests.support.upload import (
    BASE,
    all_rows,
    heic,
    intents,
    jpeg,
    make_collection,
    object_bytes,
    png,
    post_files,
    record_dispatch,
    step_runs,
    stored,
)


async def test_batch_over_max_422(uploads):
    uploads.app.state.sm_images.settings.batch_max = 2
    cid = await make_collection(uploads)
    files = [(f"{n}.jpg", jpeg(), "image/jpeg") for n in range(3)]
    got = await post_files(uploads, cid, files)
    assert got.status_code == 422, got.text
    assert got.json()["code"] == constants.CODE_BATCH_TOO_LARGE
    assert await all_rows(uploads) == []


async def test_over_threshold_requires_direct(uploads):
    settings = uploads.app.state.sm_images.settings
    big = jpeg(size=(64, 64))
    settings.direct_upload_threshold = len(big) - 1
    cid = await make_collection(uploads)
    one = await post_files(uploads, cid, [("big.jpg", big, "image/jpeg")])
    assert one.status_code == 413, one.text
    assert one.json()["code"] == constants.CODE_USE_DIRECT_UPLOAD

    # In a batch the same file is reported, and the small one still lands.
    two = await post_files(
        uploads, cid, [("big.jpg", big, "image/jpeg"), ("small.jpg", jpeg(), "image/jpeg")]
    )
    assert two.status_code == 200, two.text
    big_r, small_r = two.json()["results"]
    assert (big_r["status"], big_r["code"]) == ("error", constants.CODE_USE_DIRECT_UPLOAD)
    assert small_r["status"] == "created"
    assert len(await all_rows(uploads)) == 1


async def test_batch_isolates_a_bad_file(uploads, monkeypatch):
    sent = record_dispatch(monkeypatch)
    cid = await make_collection(uploads)
    got = await post_files(
        uploads,
        cid,
        [
            ("a.jpg", jpeg(), "image/jpeg"),
            ("nope.png", b"not an image at all", "image/png"),
            ("c.png", png(), "image/png"),
        ],
    )
    assert got.status_code == 200, got.text
    statuses = [(r["filename"], r["status"]) for r in got.json()["results"]]
    assert statuses == [("a.jpg", "created"), ("nope.png", "error"), ("c.png", "created")]
    rows = await all_rows(uploads)
    assert sorted(r.filename for r in rows) == ["a.jpg", "c.png"]
    assert stored(uploads.storage) == sorted(r.storage_key for r in rows)
    assert await intents(uploads) == []  # cleared with the rows that reference them
    assert sorted(sent) == sorted(r.id for r in rows)  # dispatched after commit
    coll = (await all_rows(uploads, Collection))[0]
    assert coll.image_count == 2


async def test_metadata_by_filename_sets_manual_location_group_and_properties(uploads):
    cid = await make_collection(uploads)
    meta = {
        "a.jpg": {
            "lat": 0,
            "lng": 0,
            "captured_at": "2026-05-01T10:00:00",
            "external_id": 42,
            "group_key": "P1",
            "group_role": "north",
            "properties": {"plot": "7"},
        },
        "b.jpg": {"lat": 48.2},
    }
    got = await post_files(
        uploads,
        cid,
        [("a.jpg", jpeg(), "image/jpeg"), ("b.jpg", jpeg(color="blue"), "image/jpeg")],
        metadata=json.dumps(meta),
    )
    assert got.status_code == 200, got.text
    rows = {r.filename: r for r in await all_rows(uploads)}
    a, b = rows["a.jpg"], rows["b.jpg"]
    assert (a.lat, a.lng, a.location_source) == (0.0, 0.0, LocationSource.MANUAL)  # (0,0) is valid
    assert a.captured_at.isoformat().startswith("2026-05-01T10:00:00")
    assert (a.external_source, a.external_id) == (constants.SOURCE_UPLOAD, "42")
    assert a.properties == {"plot": "7"} and a.group_role == "north"
    (group,) = await all_rows(uploads, Group)
    assert (a.group_id, group.key) == (group.id, "P1")
    assert (b.lat, b.lng, b.location_source) == (None, None, None)  # a lone latitude is dropped
    coll = (await all_rows(uploads, Collection))[0]
    assert (coll.image_count, coll.located_count) == (2, 1)
    assert (coll.bbox_minx, coll.bbox_miny) == (0.0, 0.0)


async def test_bad_metadata_is_422_and_stores_nothing(uploads):
    cid = await make_collection(uploads)
    bad = json.dumps({"a.jpg": {"lat": 91}})
    got = await post_files(uploads, cid, [("a.jpg", jpeg(), "image/jpeg")], metadata=bad)
    assert got.status_code == 422, got.text
    assert got.json()["code"] == constants.CODE_INVALID_METADATA
    assert await all_rows(uploads) == [] and stored(uploads.storage) == []


async def test_pending_step_runs_for_enabled_steps_only(uploads):
    cid = await make_collection(uploads)
    async with uploads.db_state.session_factory() as s:
        coll = (await s.execute(select(Collection))).scalars().one()
        coll.pipeline_config = {
            "steps": {"exif": {}, "renditions": {"enabled": True}, "quality": {"enabled": False}}
        }
        await s.commit()
    got = await post_files(uploads, cid, [("a.jpg", jpeg(), "image/jpeg")])
    assert got.status_code == 200, got.text
    assert await step_runs(uploads) == [("exif", "pending"), ("renditions", "pending")]


async def test_image_added_is_published_after_commit(uploads):
    seen: list[ImageAdded] = []
    uploads.app.state.sm.event_bus.subscribe(ImageAdded, seen.append)
    cid = await make_collection(uploads)
    got = await post_files(uploads, cid, [("a.jpg", jpeg(), "image/jpeg")])
    (only,) = got.json()["results"]
    assert [(e.collection_id, e.image_id, e.source) for e in seen] == [
        (cid, only["id"], constants.SOURCE_UPLOAD)
    ]


async def test_hash_dedupe_off_by_default(uploads):
    cid = await make_collection(uploads)
    same = jpeg()
    first = await post_files(uploads, cid, [("a.jpg", same, "image/jpeg")])
    second = await post_files(uploads, cid, [("b.jpg", same, "image/jpeg")])
    assert first.json()["results"][0]["status"] == "created"
    assert second.json()["results"][0]["status"] == "created"
    assert len(await all_rows(uploads)) == 2

    uploads.app.state.sm_images.settings.dedupe_by_hash = True
    third = await post_files(uploads, cid, [("c.jpg", same, "image/jpeg")])
    (r,) = third.json()["results"]
    assert r["status"] == "duplicate"
    assert r["id"] == first.json()["results"][0]["id"]
    assert len(await all_rows(uploads)) == 2
    assert len(stored(uploads.storage)) == 2  # the duplicate's object never stays
    assert await intents(uploads) == []


async def test_heic_upload_processes(uploads):
    cid = await make_collection(uploads)
    got = await post_files(uploads, cid, [("phone.HEIC", heic(size=(16, 8)), "image/heic")])
    assert got.status_code == 200, got.text
    (row,) = await all_rows(uploads)
    assert (row.content_type, row.width, row.height) == ("image/heic", 16, 8)
    assert row.storage_key.endswith("/original.heic")


async def test_original_never_rewritten(uploads):
    """The stored original is the uploaded bytes, at the key the row was born
    with; a later duplicate of the same external id does not touch it.
    Later tasks (EXIF, anonymize, renditions) extend this test."""
    cid = await make_collection(uploads)
    original = jpeg(size=(32, 24))
    meta = json.dumps({"a.jpg": {"external_id": "x1"}})
    await post_files(uploads, cid, [("a.jpg", original, "image/jpeg")], metadata=meta)
    (row,) = await all_rows(uploads)
    key = row.storage_key
    again = await post_files(
        uploads, cid, [("a.jpg", jpeg(size=(32, 24), color="blue"), "image/jpeg")], metadata=meta
    )
    assert again.json()["results"][0]["status"] == "duplicate"
    (row,) = await all_rows(uploads)
    assert row.storage_key == key
    assert object_bytes(uploads.storage, key) == original
    assert stored(uploads.storage) == [key]


async def test_upload_needs_edit_on_the_collection(uploads):
    cid = await make_collection(uploads)
    viewer = as_user("vic", ("images.view",))
    async with uploads.db_state.session_factory() as s:
        coll = await s.get(Collection, uuid.UUID(cid))
        s.add(share(coll, "vic", "view"))
        await s.commit()
    got = await post_files(uploads, cid, [("a.jpg", jpeg(), "image/jpeg")], headers=viewer)
    assert got.status_code == 403, got.text
    stranger = as_user("sam", ("images.view",))
    got = await post_files(uploads, cid, [("a.jpg", jpeg(), "image/jpeg")], headers=stranger)
    assert got.status_code == 404
    anon = await uploads.post(f"{BASE}/{cid}/images", files=[("files", ("a.jpg", jpeg()))])
    assert anon.status_code == 401
    assert await all_rows(uploads) == []
