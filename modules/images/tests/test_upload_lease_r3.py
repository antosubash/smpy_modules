"""Direct-upload lease, round 3 of the phase 2 review.

* the reaper's takeover commits before any storage cleanup, so a cleanup that
  fails after deleting the object cannot hand the old claim back;
* ``complete`` renews its lease between phases and stops once it is gone.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_images import constants
from sm_images.errors import UploadNotFound
from sm_images.ingest import direct
from sm_images.ingest import upload_session as state
from sm_images.ingest.service import IngestService
from sm_images.models import UploadStatus
from sm_images.storage import ImageStore

from tests.test_direct_upload import complete
from tests.test_upload_lease import _row, _update
from tests.test_upload_reaper import _one_part_in, _parts_exist, _reap
from tests.test_upload_session import _uploaded, ticket_of
from tests.upload_support import all_rows, make_collection, stored


@pytest.fixture(autouse=True)
def _small_parts(monkeypatch):
    monkeypatch.setattr(constants, "DIRECT_PART_BYTES", 400)


async def _expired_claim(uploads, ticket) -> uuid.UUID:
    token = uuid.uuid4()
    await _update(
        uploads,
        ticket,
        status=UploadStatus.COMPLETING,
        claim_token=token,
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    return token


async def test_a_cleanup_failing_after_the_delete_keeps_the_takeover(uploads, monkeypatch):
    ticket = await _one_part_in(uploads, await make_collection(uploads))
    old = await _expired_claim(uploads, ticket)
    real = ImageStore.delete_keys

    async def deletes_then_fails(self, keys):
        await real(self, keys)
        raise RuntimeError("storage hiccup after the delete")

    monkeypatch.setattr(ImageStore, "delete_keys", deletes_then_fails)
    assert await _reap(uploads, datetime.now(UTC)) == 0  # failed, logged
    row = await _row(uploads, ticket)
    assert row.status is UploadStatus.ABORTED and row.claim_token != old
    assert row.cleaned_at is None
    async with uploads.db_state.session_factory() as s:
        with pytest.raises(UploadNotFound):
            await state.renew(s, ticket, old)
        with pytest.raises(UploadNotFound):
            await state.finish(s, ticket, old)

    monkeypatch.setattr(ImageStore, "delete_keys", real)
    assert await _reap(uploads, datetime.now(UTC)) == 1
    assert (await _row(uploads, ticket)).cleaned_at is not None
    assert not _parts_exist(uploads, ticket)


async def test_renew_extends_only_the_holders_lease(uploads):
    ticket = await _one_part_in(uploads, await make_collection(uploads))
    token = uuid.uuid4()
    soon = datetime.now(UTC) + timedelta(minutes=1)
    await _update(
        uploads, ticket, status=UploadStatus.COMPLETING, claim_token=token, lease_expires_at=soon
    )
    async with uploads.db_state.session_factory() as s:
        with pytest.raises(UploadNotFound):
            await state.renew(s, ticket, uuid.uuid4())
        assert (await _row(uploads, ticket)).lease_expires_at == soon
        await state.renew(s, ticket, token)
    lease = (await _row(uploads, ticket)).lease_expires_at
    assert lease > datetime.now(UTC) + state.COMPLETE_LEASE - timedelta(minutes=1)


async def _overtake(uploads, ticket) -> None:
    await _update(uploads, ticket, lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert await _reap(uploads, datetime.now(UTC)) == 1


@pytest.mark.parametrize("phase", ["assembly", "inspection"])
async def test_a_renew_after_a_takeover_stops_the_completer(uploads, monkeypatch, phase):
    """The reaper takes the lease over during a phase of ``complete`` (assembling
    the parts, or reading the object back to inspect it): the renew after that
    phase fails, and the completer never ingests."""
    _, body, parts, _ = await _uploaded(uploads)
    ticket = ticket_of(body["upload_id"])
    ingested: list[int] = []
    if phase == "assembly":
        real_assemble = direct._assemble

        async def overtaken_assembly(store, ticket_, claimed):
            await real_assemble(store, ticket_, claimed)
            await _overtake(uploads, ticket)

        monkeypatch.setattr(direct, "_assemble", overtaken_assembly)
    else:
        real_stream = ImageStore.stream_range

        async def stream_then_overtaken(self, key, start, end):
            chunks = [c async for c in await real_stream(self, key, start, end)]
            await _overtake(uploads, ticket)

            async def again():
                for c in chunks:
                    yield c

            return again()

        monkeypatch.setattr(ImageStore, "stream_range", stream_then_overtaken)

    async def spy(self, *args, **kwargs):
        ingested.append(1)
        raise AssertionError("the completer ingested after losing its lease")

    monkeypatch.setattr(IngestService, "add_image", spy)
    got = await complete(uploads, body["upload_id"], parts)
    assert (got.status_code, got.json()["code"]) == (404, constants.CODE_UPLOAD_NOT_FOUND)
    assert ingested == []
    assert await all_rows(uploads) == [] and stored(uploads.storage) == []
    assert (await _row(uploads, ticket)).status is UploadStatus.ABORTED
