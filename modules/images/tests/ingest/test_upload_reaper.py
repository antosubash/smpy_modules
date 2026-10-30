"""``reap_expired_uploads``: abandoned multipart uploads are reclaimable (P2-3).

The janitor (Task 15) calls it per tenant. An expired ``open`` session is
claimed ``aborted`` first, then its parts are discarded and its final key
deleted; the final key's intent stays as the janitor's backstop.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_images import constants
from sm_images.ingest.upload_reaper import reap_expired_uploads
from sm_images.models import UploadSession, UploadStatus
from sm_images.storage import ImageStore

from tests.ingest.test_upload_session import sessions, ticket_of
from tests.support.direct import start
from tests.support.upload import OLGA, intents, jpeg, make_collection


@pytest.fixture(autouse=True)
def _small_parts(monkeypatch):
    monkeypatch.setattr(constants, "DIRECT_PART_BYTES", 400)


async def _one_part_in(uploads, cid: str):
    """An upload with its first part stored and nothing else."""
    data = jpeg(size=(64, 48))
    body = (await start(uploads, cid, data)).json()
    put = await uploads.put(body["part_urls"][0], content=data[:400], headers=OLGA)
    assert put.status_code == 200, put.text
    return ticket_of(body["upload_id"])


async def _set(uploads, ticket, *, expires_at: datetime, status: UploadStatus | None = None):
    async with uploads.db_state.session_factory() as s:
        row = await s.get(UploadSession, uuid.UUID(ticket.session))
        row.expires_at = expires_at
        if status is not None:
            row.status = status
        await s.commit()


async def _reap(uploads, now: datetime, cap: int = 100) -> int:
    async with uploads.db_state.session_factory() as s:
        n = await reap_expired_uploads(s, ImageStore(uploads.storage), now, cap)
        await s.commit()
    return n


def _parts_exist(uploads, ticket) -> bool:
    return uploads.storage._parts_dir(ticket.upload).exists()


async def test_an_expired_open_session_is_aborted_and_its_parts_removed(uploads):
    cid = await make_collection(uploads)
    ticket = await _one_part_in(uploads, cid)
    now = datetime.now(UTC)
    await _set(uploads, ticket, expires_at=now - timedelta(seconds=1))
    assert _parts_exist(uploads, ticket)

    assert await _reap(uploads, now) == 1
    assert not _parts_exist(uploads, ticket)
    assert not await uploads.storage.exists(ticket.key)
    assert (await sessions(uploads))[0].status is UploadStatus.ABORTED
    assert await intents(uploads) == [ticket.key]  # the janitor's backstop stays
    assert await _reap(uploads, now) == 0  # aborted is final


async def test_a_live_session_and_the_cap_are_respected(uploads):
    cid = await make_collection(uploads)
    live, old1, old2 = [await _one_part_in(uploads, cid) for _ in range(3)]
    now = datetime.now(UTC)
    for t in (old1, old2):
        await _set(uploads, t, expires_at=now - timedelta(minutes=5))

    assert await _reap(uploads, now, cap=1) == 1
    assert await _reap(uploads, now, cap=1) == 1
    assert await _reap(uploads, now, cap=1) == 0
    assert _parts_exist(uploads, live)
    by_id = {str(r.id): r.status for r in await sessions(uploads)}
    assert by_id[live.session] is UploadStatus.OPEN
    assert {by_id[old1.session], by_id[old2.session]} == {UploadStatus.ABORTED}
