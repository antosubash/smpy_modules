"""Direct uploads on the filesystem backend: parts relayed through the app.

The image is staged at its final ``original_key`` and ingested in place on
``complete``; the stored object is re-checked there, not the declared size.
"""

from __future__ import annotations

import pytest
from sm_images import constants
from sm_images.models import Image

from tests.stub_auth import as_user
from tests.upload_support import (
    BASE,
    OLGA,
    all_rows,
    intents,
    jpeg,
    make_collection,
    object_bytes,
    stored,
)

UPLOADS = "/api/images/uploads"


async def start(client, cid, data: bytes, headers=OLGA, **extra):
    body = {"filename": "big.jpg", "size": len(data), **extra}
    return await client.post(f"{BASE}/{cid}/uploads", json=body, headers=headers)


async def send_parts(client, created: dict, data: bytes, headers=OLGA) -> list[dict]:
    size = created["part_size"]
    parts = []
    for n, url in enumerate(created["part_urls"], start=1):
        chunk = data[(n - 1) * size : n * size]
        put = await client.put(url, content=chunk, headers=headers)
        assert put.status_code == 200, put.text
        parts.append({"no": n, "etag": put.json()["etag"]})
    return parts


async def complete(client, upload_id: str, parts, headers=OLGA, **body):
    return await client.post(
        f"{UPLOADS}/{upload_id}/complete", json={"parts": parts, **body}, headers=headers
    )


@pytest.fixture
def small_parts(monkeypatch):
    """Two parts for a test-sized image."""
    monkeypatch.setattr(constants, "DIRECT_PART_BYTES", 400)


async def test_direct_upload_relays_parts_and_ingests_in_place(uploads, small_parts):
    data = jpeg(size=(64, 48))
    assert len(data) > 400
    cid = await make_collection(uploads)
    created = await start(uploads, cid, data)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["direct"] is False and body["part_size"] == 400
    assert all(u.startswith(f"{UPLOADS}/") and "/parts/" in u for u in body["part_urls"])
    assert len(await intents(uploads)) == 1  # the staged key's intent, from the start

    parts = await send_parts(uploads, body, data)
    done = await complete(uploads, body["upload_id"], parts, metadata={"lat": 1, "lng": 2})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "created" and done.json()["filename"] == "big.jpg"
    (row,) = await all_rows(uploads)
    assert str(row.id) == done.json()["id"]
    assert (row.size_bytes, row.content_type, row.lat, row.lng) == (len(data), "image/jpeg", 1, 2)
    assert stored(uploads.storage) == [row.storage_key]  # staged at the final key, no copy
    assert object_bytes(uploads.storage, row.storage_key) == data
    assert await intents(uploads) == []

    replay = await complete(uploads, body["upload_id"], parts)
    assert (replay.status_code, replay.json()["id"]) == (200, done.json()["id"])
    # abort after completion never deletes the original a row owns
    assert (await uploads.delete(f"{UPLOADS}/{body['upload_id']}", headers=OLGA)).status_code == 204
    assert stored(uploads.storage) == [row.storage_key]


async def test_direct_upload_complete_checks_size(uploads, small_parts):
    """The limit is checked against the *stored* object at completion, so a
    lowered limit (or an object that differs from the claim) is refused and the
    staged object removed."""
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data)).json()
    parts = await send_parts(uploads, body, data)
    uploads.app.state.sm_images.settings.max_image_bytes = len(data) - 1
    done = await complete(uploads, body["upload_id"], parts)
    assert done.status_code == 413, done.text
    assert done.json()["code"] == constants.CODE_FILE_TOO_LARGE
    assert await all_rows(uploads) == []
    assert stored(uploads.storage) == []


async def test_declared_size_over_the_limit_is_refused_up_front(uploads):
    uploads.app.state.sm_images.settings.max_image_bytes = 1000
    cid = await make_collection(uploads)
    got = await start(uploads, cid, b"x" * 1001)
    assert (got.status_code, got.json()["code"]) == (413, constants.CODE_FILE_TOO_LARGE)


async def test_missing_or_short_part_is_refused(uploads, small_parts):
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data)).json()
    short = await uploads.put(body["part_urls"][0], content=data[:10], headers=OLGA)
    assert short.status_code == 422, short.text
    missing = await complete(uploads, body["upload_id"], [])
    assert (missing.status_code, missing.json()["code"]) == (409, constants.CODE_PARTS_MISMATCH)


async def test_a_non_image_is_415_and_its_staged_object_goes(uploads, small_parts):
    data = b"\0" * 700
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data)).json()
    parts = await send_parts(uploads, body, data)
    done = await complete(uploads, body["upload_id"], parts)
    assert done.status_code == 415, done.text
    assert stored(uploads.storage) == []


async def test_upload_id_is_bound_to_its_user_and_unforgeable(uploads, small_parts):
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data)).json()
    sam = as_user("sam", ("images.view", "images.create"))
    other = await uploads.put(body["part_urls"][0], content=data[:400], headers=sam)
    assert other.status_code == 404
    forged = body["upload_id"][:-4] + ("AAAA" if not body["upload_id"].endswith("AAAA") else "BBBB")
    for url in (f"{UPLOADS}/{forged}/complete", f"{UPLOADS}/not-a-token/complete"):
        got = await uploads.post(url, json={"parts": []}, headers=OLGA)
        assert (got.status_code, got.json()["code"]) == (404, constants.CODE_UPLOAD_NOT_FOUND)


async def test_abort_discards_the_parts(uploads, small_parts):
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data)).json()
    await send_parts(uploads, body, data)
    gone = await uploads.delete(f"{UPLOADS}/{body['upload_id']}", headers=OLGA)
    assert gone.status_code == 204
    after = await complete(uploads, body["upload_id"], [])
    assert after.status_code == 404
    assert await all_rows(uploads, Image) == []
    assert stored(uploads.storage) == []
