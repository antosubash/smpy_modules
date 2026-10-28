"""Base64 upload, and external-id dedupe including the race the pre-check misses.

The race is the portal's phase-2 static finding: a concurrent duplicate lost on
the unique index answered 500. Here the IntegrityError re-checks identity and
answers ``duplicate`` with the winner's id. Runs on Postgres too
(``SM_TEST_DATABASE_URL``).
"""

from __future__ import annotations

import base64
import uuid

from sm_images import constants
from sm_images.ingest import Duplicate, IngestMeta, IngestService, dedupe
from sm_images.models import Collection, Image
from sm_images.settings import ImagesSettings
from sm_images.storage import ImageStore
from sqlalchemy import select

from tests.upload_support import BASE, OLGA, all_rows, intents, jpeg, make_collection, stored


def b64(data: bytes, *, url: bool = False) -> str:
    text = base64.b64encode(data).decode()
    return f"data:image/jpeg;base64,{text}" if url else text


async def post(client, cid, **body):
    return await client.post(f"{BASE}/{cid}/images/base64", json=body, headers=OLGA)


async def test_base64_dedupes_external_id(uploads):
    cid = await make_collection(uploads)
    first = await post(uploads, cid, filename="a.jpg", data=b64(jpeg()), external_id="ext-1")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "created"
    again = await post(
        uploads, cid, filename="b.jpg", data=b64(jpeg(color="blue"), url=True), external_id="ext-1"
    )
    assert again.json() == {
        "filename": "b.jpg",
        "status": "duplicate",
        "id": first.json()["id"],
        "code": None,
        "detail": None,
    }
    (row,) = await all_rows(uploads)
    assert (row.external_source, row.external_id) == (constants.SOURCE_UPLOAD, "ext-1")
    assert len(stored(uploads.storage)) == 1

    # Another source is another identity.
    other = await post(
        uploads, cid, data=b64(jpeg()), external_id="ext-1", external_source="survey"
    )
    assert other.json()["status"] == "created"


async def test_base64_rejects_bad_payloads(uploads):
    cid = await make_collection(uploads)
    bad = await post(uploads, cid, data="!!!not-base64!!!")
    assert (bad.status_code, bad.json()["code"]) == (422, constants.CODE_INVALID_BASE64)
    uploads.app.state.sm_images.settings.max_image_bytes = 100
    big = await post(uploads, cid, data=b64(jpeg(size=(64, 64))))
    assert (big.status_code, big.json()["code"]) == (413, constants.CODE_FILE_TOO_LARGE)
    assert await all_rows(uploads) == []


async def test_a_trashed_image_still_owns_its_external_id(uploads):
    cid = await make_collection(uploads)
    first = (await post(uploads, cid, data=b64(jpeg()), external_id="z")).json()
    gone = await uploads.delete(f"/api/images/images/{first['id']}", headers=OLGA)
    assert gone.status_code == 204
    again = (await post(uploads, cid, data=b64(jpeg()), external_id="z")).json()
    assert (again["status"], again["id"]) == ("duplicate", first["id"])


async def test_lost_race_on_the_unique_index_is_a_duplicate_not_a_500(uploads, monkeypatch):
    """The pre-check sees nothing (the other request had not committed yet), the
    insert loses on ``uq_images_image_external``: the answer is the winner."""
    cid = uuid.UUID(await make_collection(uploads))
    factory = uploads.db_state.session_factory
    async with factory() as s:
        winner = Image(
            collection_id=cid,
            storage_key="images/default/w/original.jpg",
            filename="w.jpg",
            content_type="image/jpeg",
            size_bytes=1,
            external_source=constants.SOURCE_UPLOAD,
            external_id="race",
        )
        s.add(winner)
        await s.commit()

    async def blind(*_a, **_k):
        return None

    calls = []
    real = dedupe.find_external

    async def counted(*a, **k):
        calls.append(1)
        return await (blind if len(calls) == 1 else real)(*a, **k)

    monkeypatch.setattr(dedupe, "find_external", counted)
    async with factory() as db:
        coll = await db.get(Collection, cid)
        ingest = IngestService(
            db, ImageStore(uploads.storage), ImagesSettings(), intent_factory=factory
        )
        await db.execute(select(Image.id))  # a read, then the race
        out = await ingest.add_image(
            coll,
            data=jpeg(),
            filename="late.jpg",
            meta=IngestMeta(external_id="race"),
            source=constants.SOURCE_UPLOAD,
        )
        await db.commit()
    assert out == Duplicate(winner.id)
    assert len(calls) == 2  # the pre-check, then the re-check after IntegrityError
    rows = await all_rows(uploads)
    assert [r.id for r in rows] == [winner.id]
    assert stored(uploads.storage) == []  # the loser's object was removed
    assert await intents(uploads) == []
    coll_row = (await all_rows(uploads, Collection))[0]
    assert coll_row.image_count == 0  # the loser's stats rolled back with its savepoint
