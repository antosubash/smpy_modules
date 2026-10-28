"""Durable direct-upload state (phase 2 review, P1-2).

``images_upload_session`` is authoritative: ``complete`` claims it
``open -> completing`` before touching the parts and finishes it
``completed`` with the image row; ``abort`` claims it ``open -> aborted``
before deleting anything. Whoever loses the claim backs off, so an abort can
never delete an original a ``complete`` has validated and is about to insert.

The interleavings are driven deterministically: the second call is issued from
inside the first, at the exact point the review named.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_images import constants
from sm_images.ingest import direct
from sm_images.ingest.service import IngestService
from sm_images.models import UploadSession, UploadStatus

from tests.stub_auth import user_uuid
from tests.test_direct_upload import UPLOADS, complete, send_parts, start
from tests.upload_support import OLGA, all_rows, jpeg, make_collection, stored


@pytest.fixture(autouse=True)
def _small_parts(monkeypatch):
    monkeypatch.setattr(constants, "DIRECT_PART_BYTES", 400)


def ticket_of(upload_id: str) -> direct.Ticket:
    return direct.load_ticket(upload_id, secret="images-test-secret", owner=user_uuid("olga"))


async def sessions(client) -> list[UploadSession]:
    return await all_rows(client, UploadSession)


async def _uploaded(uploads) -> tuple[str, dict, list[dict], bytes]:
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data)).json()
    parts = await send_parts(uploads, body, data)
    return cid, body, parts, data


async def test_start_records_an_open_session(uploads):
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data)).json()
    ticket = ticket_of(body["upload_id"])
    (row,) = await sessions(uploads)
    assert str(row.id) == ticket.session
    assert row.status is UploadStatus.OPEN
    assert (str(row.collection_id), str(row.image_id)) == (cid, ticket.image)
    assert (row.storage_key, row.backend_upload_id) == (ticket.key, ticket.upload)
    assert (row.size, row.content_type, row.tenant_id) == (len(data), "image/jpeg", "default")
    ttl = timedelta(seconds=constants.DIRECT_UPLOAD_TTL_SECONDS)
    assert abs(row.expires_at - (datetime.now(UTC) + ttl)) < timedelta(minutes=1)


async def test_complete_then_abort_leaves_a_completed_session(uploads):
    _, body, parts, _ = await _uploaded(uploads)
    assert (await complete(uploads, body["upload_id"], parts)).status_code == 200
    (row,) = await sessions(uploads)
    assert row.status is UploadStatus.COMPLETED
    gone = await uploads.delete(f"{UPLOADS}/{body['upload_id']}", headers=OLGA)
    assert gone.status_code == 204
    (image,) = await all_rows(uploads)
    assert stored(uploads.storage) == [image.storage_key]
    assert (await sessions(uploads))[0].status is UploadStatus.COMPLETED


async def test_abort_during_complete_is_409_and_the_original_survives(uploads, monkeypatch):
    """The review's race: ``complete`` has assembled and validated the object and
    is about to insert its row when ``abort`` arrives."""
    _, body, parts, _ = await _uploaded(uploads)
    answers: list[tuple[int, str | None]] = []
    real = IngestService.add_image

    async def abort_first(self, *args, **kwargs):
        got = await uploads.delete(f"{UPLOADS}/{body['upload_id']}", headers=OLGA)
        answers.append((got.status_code, got.json().get("code") if got.content else None))
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(IngestService, "add_image", abort_first)
    done = await complete(uploads, body["upload_id"], parts)
    assert answers == [(409, constants.CODE_UPLOAD_IN_PROGRESS)]
    assert done.status_code == 200, done.text
    (image,) = await all_rows(uploads)
    assert stored(uploads.storage) == [image.storage_key]
    assert (await sessions(uploads))[0].status is UploadStatus.COMPLETED


async def test_complete_during_abort_is_404_and_nothing_is_ingested(uploads, monkeypatch):
    """The other order: ``abort`` has claimed the session and is discarding the
    parts when ``complete`` arrives."""
    _, body, parts, _ = await _uploaded(uploads)
    backend = uploads.storage
    answers: list[int] = []
    real = type(backend).abort_multipart

    async def complete_first(self, key, upload_id):
        got = await complete(uploads, body["upload_id"], parts)
        answers.append(got.status_code)
        return await real(self, key, upload_id)

    monkeypatch.setattr(type(backend), "abort_multipart", complete_first)
    gone = await uploads.delete(f"{UPLOADS}/{body['upload_id']}", headers=OLGA)
    assert gone.status_code == 204
    assert answers == [404]
    assert await all_rows(uploads) == [] and stored(uploads.storage) == []
    assert (await sessions(uploads))[0].status is UploadStatus.ABORTED


async def test_a_second_complete_while_one_runs_is_409(uploads, monkeypatch):
    _, body, parts, _ = await _uploaded(uploads)
    answers: list[int] = []
    real = IngestService.add_image

    async def again_first(self, *args, **kwargs):
        answers.append((await complete(uploads, body["upload_id"], parts)).status_code)
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(IngestService, "add_image", again_first)
    assert (await complete(uploads, body["upload_id"], parts)).status_code == 200
    assert answers == [409]
    assert len(await all_rows(uploads)) == 1


async def test_a_refused_part_set_reopens_the_session(uploads):
    """A missing part is the client's to fix: the session goes back to ``open``."""
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data)).json()
    missing = await complete(uploads, body["upload_id"], [])
    assert missing.status_code == 409
    assert (await sessions(uploads))[0].status is UploadStatus.OPEN
    parts = await send_parts(uploads, body, data)
    assert (await complete(uploads, body["upload_id"], parts)).status_code == 200


async def test_refused_bytes_abort_the_session(uploads):
    data = b"\0" * 700
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data)).json()
    parts = await send_parts(uploads, body, data)
    assert (await complete(uploads, body["upload_id"], parts)).status_code == 415
    assert (await sessions(uploads))[0].status is UploadStatus.ABORTED
    assert stored(uploads.storage) == []


async def test_an_expired_session_cannot_complete(uploads):
    _, body, parts, _ = await _uploaded(uploads)
    async with uploads.db_state.session_factory() as s:
        row = await s.get(UploadSession, uuid.UUID(ticket_of(body["upload_id"]).session))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
    got = await complete(uploads, body["upload_id"], parts)
    assert (got.status_code, got.json()["code"]) == (404, constants.CODE_UPLOAD_NOT_FOUND)
    assert await all_rows(uploads) == []
