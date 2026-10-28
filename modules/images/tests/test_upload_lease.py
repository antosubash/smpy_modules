"""Direct-upload sessions, round 2 of the phase 2 review.

* ``completing`` is a fenced lease: the claim writes a token and an expiry; the
  reaper takes over only an expired lease, and a completer that lost its lease
  cannot commit its row (``finish`` matches the token or rolls back);
* a failed abort cleanup is durable (``cleaned_at`` stays NULL) and the reaper
  retries it;
* parts are accepted only while the session is ``open``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from file_storage.backends.filesystem import FilesystemBackend
from sm_images import constants
from sm_images.errors import UploadNotFound
from sm_images.ingest import upload_session as state
from sm_images.ingest.service import IngestService
from sm_images.models import Image, UploadSession, UploadStatus

from tests.pg_support import USING_POSTGRES
from tests.test_direct_upload import UPLOADS, complete, send_parts, start
from tests.test_upload_reaper import _one_part_in, _parts_exist, _reap
from tests.test_upload_session import _uploaded, ticket_of
from tests.upload_support import OLGA, all_rows, jpeg, make_collection, stored


@pytest.fixture(autouse=True)
def _small_parts(monkeypatch):
    monkeypatch.setattr(constants, "DIRECT_PART_BYTES", 400)


async def _update(uploads, ticket, **values) -> None:
    async with uploads.db_state.session_factory() as s:
        row = await s.get(UploadSession, uuid.UUID(ticket.session))
        for name, value in values.items():
            setattr(row, name, value)
        await s.commit()


async def _row(uploads, ticket) -> UploadSession:
    async with uploads.db_state.session_factory() as s:
        return await s.get(UploadSession, uuid.UUID(ticket.session))


# -- the completing lease ----------------------------------------------------


async def test_the_complete_claim_writes_a_token_and_a_lease(uploads, monkeypatch):
    _, body, parts, _ = await _uploaded(uploads)
    ticket = ticket_of(body["upload_id"])
    seen: list[UploadSession] = []
    real = IngestService.add_image

    async def peek(self, *args, **kwargs):
        seen.append(await _row(uploads, ticket))
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(IngestService, "add_image", peek)
    assert (await complete(uploads, body["upload_id"], parts)).status_code == 200
    (during,) = seen
    assert during.status is UploadStatus.COMPLETING and during.claim_token is not None
    assert datetime.now(UTC) < during.lease_expires_at <= datetime.now(UTC) + state.COMPLETE_LEASE


async def test_the_reaper_takes_over_an_expired_lease(uploads):
    ticket = await _one_part_in(uploads, await make_collection(uploads))
    now = datetime.now(UTC)
    old = uuid.uuid4()
    await _update(
        uploads,
        ticket,
        status=UploadStatus.COMPLETING,
        claim_token=old,
        lease_expires_at=now - timedelta(seconds=1),
    )
    assert await _reap(uploads, now) == 1
    row = await _row(uploads, ticket)
    assert row.status is UploadStatus.ABORTED and row.claim_token != old
    assert row.cleaned_at is not None and not _parts_exist(uploads, ticket)


async def test_a_held_lease_is_never_reaped(uploads):
    """However long ago the session itself expired, a live lease keeps it."""
    ticket = await _one_part_in(uploads, await make_collection(uploads))
    now = datetime.now(UTC)
    await _update(
        uploads,
        ticket,
        status=UploadStatus.COMPLETING,
        claim_token=uuid.uuid4(),
        expires_at=now - timedelta(days=2),
        lease_expires_at=now + timedelta(minutes=5),
    )
    assert await _reap(uploads, now) == 0
    assert _parts_exist(uploads, ticket)
    assert (await _row(uploads, ticket)).status is UploadStatus.COMPLETING


async def test_finish_without_the_claim_rolls_the_insert_back(uploads):
    """A completer whose lease was taken over cannot commit its image row."""
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    ticket = ticket_of((await start(uploads, cid, data)).json()["upload_id"])
    await _update(uploads, ticket, status=UploadStatus.COMPLETING, claim_token=uuid.uuid4())
    async with uploads.db_state.session_factory() as s:
        s.add(
            Image(
                id=uuid.UUID(ticket.image),
                collection_id=uuid.UUID(cid),
                storage_key=ticket.key,
                filename="big.jpg",
                content_type="image/jpeg",
                size_bytes=len(data),
            )
        )
        await s.flush()
        with pytest.raises(UploadNotFound):
            await state.finish(s, ticket, uuid.uuid4())
        await s.commit()
    assert await all_rows(uploads) == []
    assert (await _row(uploads, ticket)).status is UploadStatus.COMPLETING


@pytest.mark.skipif(not USING_POSTGRES, reason="needs real connections (Postgres)")
async def test_a_completer_overtaken_by_the_reaper_commits_no_row(uploads, monkeypatch):
    _, body, parts, _ = await _uploaded(uploads)
    ticket = ticket_of(body["upload_id"])
    real = state.finish

    async def overtaken(db, ticket_, token):
        await _update(uploads, ticket, lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        assert await _reap(uploads, datetime.now(UTC)) == 1
        return await real(db, ticket_, token)

    monkeypatch.setattr(state, "finish", overtaken)
    got = await complete(uploads, body["upload_id"], parts)
    assert (got.status_code, got.json()["code"]) == (404, constants.CODE_UPLOAD_NOT_FOUND)
    assert await all_rows(uploads) == []
    assert (await _row(uploads, ticket)).status is UploadStatus.ABORTED


# -- durable abort cleanup ---------------------------------------------------


async def test_a_clean_abort_records_cleaned_at(uploads):
    ticket = await _one_part_in(uploads, await make_collection(uploads))
    gone = await uploads.delete(f"{UPLOADS}/{ticket_of_id(ticket)}", headers=OLGA)
    assert gone.status_code == 204
    assert (await _row(uploads, ticket)).cleaned_at is not None


async def test_a_failed_abort_cleanup_is_retried_by_the_reaper(uploads, monkeypatch):
    ticket = await _one_part_in(uploads, await make_collection(uploads))
    real = FilesystemBackend.abort_multipart
    failures = [1]

    async def flaky(self, key, upload_id):
        if failures:
            failures.pop()
            raise RuntimeError("storage is down")
        return await real(self, key, upload_id)

    monkeypatch.setattr(FilesystemBackend, "abort_multipart", flaky)
    with pytest.raises(RuntimeError):
        await uploads.delete(f"{UPLOADS}/{ticket_of_id(ticket)}", headers=OLGA)
    row = await _row(uploads, ticket)
    assert (row.status, row.cleaned_at) == (UploadStatus.ABORTED, None)
    assert _parts_exist(uploads, ticket)

    assert await _reap(uploads, datetime.now(UTC)) == 1
    assert (await _row(uploads, ticket)).cleaned_at is not None
    assert not _parts_exist(uploads, ticket)
    assert await _reap(uploads, datetime.now(UTC)) == 0


# -- parts only while open ---------------------------------------------------


async def test_parts_are_refused_unless_the_session_is_open(uploads):
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    body = (await start(uploads, cid, data)).json()
    ticket = ticket_of(body["upload_id"])
    first = body["part_urls"][0]

    await _update(uploads, ticket, status=UploadStatus.COMPLETING)
    busy = await uploads.put(first, content=data[:400], headers=OLGA)
    assert (busy.status_code, busy.json()["code"]) == (409, constants.CODE_UPLOAD_NOT_OPEN)

    await _update(uploads, ticket, status=UploadStatus.OPEN)
    parts = await send_parts(uploads, body, data)
    assert (await complete(uploads, body["upload_id"], parts)).status_code == 200
    late = await uploads.put(first, content=data[:400], headers=OLGA)
    assert (late.status_code, late.json()["code"]) == (409, constants.CODE_UPLOAD_NOT_OPEN)
    assert len(stored(uploads.storage)) == 1

    other = (await start(uploads, cid, data)).json()
    assert (
        await uploads.delete(f"{UPLOADS}/{other['upload_id']}", headers=OLGA)
    ).status_code == 204
    after = await uploads.put(other["part_urls"][0], content=data[:400], headers=OLGA)
    assert (after.status_code, after.json()["code"]) == (404, constants.CODE_UPLOAD_NOT_FOUND)


def ticket_of_id(ticket) -> str:
    """The signed ``upload_id`` for a ticket the tests decoded."""
    from dataclasses import asdict

    from sm_images.ingest.ticket import serializer

    return serializer("images-test-secret").dumps(asdict(ticket))
