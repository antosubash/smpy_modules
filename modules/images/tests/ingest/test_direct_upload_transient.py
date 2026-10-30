"""Direct-upload ``complete`` after assembly: only the module's own validation
refusals (sniff mismatch, size, guards) abort the upload. Any other failure -
a database or storage blip, an unavailable service - leaves the session
``open`` with the assembled object kept, so ``complete`` can be retried, and
the retry makes exactly one image and keeps exactly one hold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_images.billing import ops as billing_ops
from sm_images.core import constants
from sm_images.core.errors import ImageTooLarge, ServiceUnavailable
from sm_images.ingest.service import IngestService
from sm_images.ingest.slots import INGEST_CLAIM
from sm_images.models import UploadSession, UploadStatus
from sm_images.services import stats
from sm_images.tenancy import DEFAULT_TENANT as T

from tests.support.direct import complete, send_parts, start
from tests.support.upload import all_rows, jpeg, make_collection, stored


async def _uploaded(client) -> tuple[str, list]:
    data = jpeg(size=(64, 48))
    cid = await make_collection(client)
    created = (await start(client, cid, data)).json()
    return created["upload_id"], await send_parts(client, created, data)


async def _status(client) -> UploadStatus:
    (row,) = await all_rows(client, UploadSession)
    return row.status


def _once(monkeypatch, owner, name: str, exc: Exception) -> None:
    real = getattr(owner, name)
    state = {"armed": True}

    def fail_once(*args, **kwargs):
        if state.pop("armed", False):
            raise exc
        return real(*args, **kwargs)

    monkeypatch.setattr(owner, name, fail_once)


def _once_async(monkeypatch, owner, name: str, exc: Exception) -> None:
    real = getattr(owner, name)
    state = {"armed": True}

    async def fail_once(*args, **kwargs):
        if state.pop("armed", False):
            raise exc
        return await real(*args, **kwargs)

    monkeypatch.setattr(owner, name, fail_once)


async def test_a_transient_failure_keeps_the_upload_open_and_a_retry_is_idempotent(
    uploads, gauge, small_parts, monkeypatch
):
    upload_id, parts = await _uploaded(uploads)
    _once_async(monkeypatch, stats, "on_image_added", RuntimeError("database blip"))
    with pytest.raises(Exception):  # noqa: B017 - an unhandled 500, raised through the transport
        await complete(uploads, upload_id, parts)
    assert await _status(uploads) is UploadStatus.OPEN
    assert await all_rows(uploads) == [] and len(stored(uploads.storage)) == 1

    retried = await complete(uploads, upload_id, parts)
    assert retried.status_code == 200, retried.text
    (row,) = await all_rows(uploads)
    assert await _status(uploads) is UploadStatus.COMPLETED
    later = datetime.now(UTC) + INGEST_CLAIM + timedelta(seconds=1)
    await billing_ops.settle(uploads.db_state.session_factory, T, now=later)
    assert len(gauge.holds) == 2  # one per attempt
    held = {h.id: h.status for h in gauge.holds.values() if h.status != "released"}
    assert held == {row.storage_hold_id: "committed"}  # the first attempt's hold went back


async def test_a_retry_after_a_late_failure_ends_with_one_hold(
    uploads, gauge, small_parts, monkeypatch
):
    """The failure comes after billing committed the attempt's hold (in the
    insert). The request's rollback must not swallow the hand-back: the hold
    is released before the retry takes its own, so a quota that fits one
    upload admits the retry and exactly one hold is left committed."""
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    created = (await start(uploads, cid, data)).json()
    parts = await send_parts(uploads, created, data)
    gauge.limit = len(data)  # room for exactly one upload
    _once_async(monkeypatch, stats, "on_image_added", RuntimeError("database blip"))
    with pytest.raises(Exception):  # noqa: B017 - an unhandled 500, raised through the transport
        await complete(uploads, created["upload_id"], parts)
    assert await _status(uploads) is UploadStatus.OPEN

    retried = await complete(uploads, created["upload_id"], parts)
    assert retried.status_code == 200, retried.text
    (row,) = await all_rows(uploads)
    live = {h.id: h.status for h in gauge.holds.values() if h.status != "released"}
    assert live == {row.storage_hold_id: "committed"}
    async with uploads.db_state.session_factory() as db:
        assert await billing_ops.unfinished(db, T, row.id) == []


async def test_an_unavailable_service_keeps_the_upload_open(
    uploads, gauge, small_parts, monkeypatch
):
    upload_id, parts = await _uploaded(uploads)
    _once(monkeypatch, IngestService, "inspect", ServiceUnavailable("try again"))
    refused = await complete(uploads, upload_id, parts)
    assert refused.status_code == 503, refused.text
    assert await _status(uploads) is UploadStatus.OPEN
    assert len(stored(uploads.storage)) == 1  # the assembled object is kept
    assert (await complete(uploads, upload_id, parts)).status_code == 200
    assert len(await all_rows(uploads)) == 1


async def test_a_guard_refusal_aborts_the_upload(uploads, gauge, small_parts, monkeypatch):
    upload_id, parts = await _uploaded(uploads)
    _once(monkeypatch, IngestService, "inspect", ImageTooLarge("too many pixels"))
    refused = await complete(uploads, upload_id, parts)
    assert (refused.status_code, refused.json()["code"]) == (413, constants.CODE_TOO_MANY_PIXELS)
    assert await _status(uploads) is UploadStatus.ABORTED
    assert stored(uploads.storage) == [] and await all_rows(uploads) == []
