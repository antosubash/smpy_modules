"""Task 18 review fixes: ZIP64 preflight, metadata budgets and parsing, delete
during upload, external sources, manual coordinates, the persisted part size,
etag-backed stores."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from file_storage.contracts.service import StorageNotFoundError
from sm_images import constants
from sm_images.errors import Conflict, NotFound
from sm_images.imports import controls, zip_import, zip_safety, zip_upload
from sm_images.imports.zip_safety import Limits, ZipRejected, inspect
from sm_images.imports.zip_source import fetch_verified
from sm_images.models import ImportJob, UploadSession
from sm_images.models.enums import JobStatus, LocationSource, UploadStatus
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select, update

from tests.pipeline_support import jpeg
from tests.zip_support import (
    EtagStore,
    import_zip,
    make_zip,
    sealed_zip,
    upload_zip,
    zip64_disguised,
)

pytestmark = pytest.mark.asyncio
BIG = Limits(max_entries=100, max_entry_bytes=10**8, max_total_bytes=10**9, max_ratio=200)


def _code(tmp_path: Path, data: bytes, limits: Limits = BIG) -> str:
    path = tmp_path / "a.zip"
    path.write_bytes(data)
    with pytest.raises(ZipRejected) as err:
        inspect(path, limits)
    return err.value.code


def _errors(row) -> list[str]:
    return [e["code"] for e in row.errors]


# --- 1. ZIP64 ------------------------------------------------------------------


async def test_zip64_record_is_capped_before_zipfile_is_built(tmp_path):
    five = make_zip([(f"{i}.jpg", b"x") for i in range(5)])
    four = Limits(max_entries=4, max_entry_bytes=10**6, max_total_bytes=10**6, max_ratio=200)
    for legacy, code in ((1, "invalid_zip"), (5, "too_many_entries"), (0xFFFF, "too_many_entries")):
        path = tmp_path / "z.zip"
        path.write_bytes(zip64_disguised(five, legacy))
        with (
            patch.object(zip_safety.zipfile, "ZipFile") as opened,
            pytest.raises(ZipRejected) as err,
        ):
            inspect(path, four)
        assert err.value.code == code, legacy
        opened.assert_not_called()
    path.write_bytes(zip64_disguised(five, 5))  # consistent and within limits: fine
    assert len(inspect(path, BIG).entries) == 5


# --- 2. metadata.json shares the budgets -----------------------------------------


async def test_metadata_counts_toward_the_budgets_and_may_appear_once(tmp_path):
    padded = b"{" + b" " * 3000 + b"}"
    capped = Limits(max_entries=10, max_entry_bytes=10**6, max_total_bytes=2000, max_ratio=10**6)
    assert _code(tmp_path, make_zip([("metadata.json", padded)]), capped) == (
        "uncompressed_too_large"
    )
    bomb = b"{" + b" " * (3 * 1024 * 1024) + b"}"
    assert _code(tmp_path, make_zip([("metadata.json", bomb)])) == "suspicious_ratio"
    twice = make_zip([("metadata.json", b"{}"), ("metadata.json", b"{}")])
    assert _code(tmp_path, twice) == "metadata_duplicate"


# --- 3. hostile metadata fails the job, never loops ------------------------------


async def test_hostile_metadata_is_invalid(tmp_path):
    huge_int = b'{"a.jpg": {"external_id": ' + b"9" * 5000 + b"}}"
    deep = b'{"a.jpg": {"properties": {"x": ' + b"[" * 100_000 + b"]" * 100_000 + b"}}}"
    shallow_but_deep = b'{"a": ' + b"[" * 100 + b"]" * 100 + b"}"
    for doc in (huge_int, deep, shallow_but_deep):
        assert _code(tmp_path, make_zip([("metadata.json", doc)])) == "metadata_invalid"


async def test_hostile_metadata_fails_the_job_terminally(imp):
    doc = b'{"a.jpg": {"external_id": ' + b"9" * 5000 + b"}}"
    job, status = await import_zip(imp, make_zip([("metadata.json", doc), ("a.jpg", jpeg())]))
    assert status == "failed"
    assert _errors(await imp.reload(job)) == ["metadata_invalid"]


async def test_an_unexpected_parse_error_fails_the_job(imp, monkeypatch):
    def broken(*a, **k):
        raise ValueError("a parser bug")

    monkeypatch.setattr(zip_import, "inspect", broken)
    job, status = await import_zip(imp, make_zip([("a.jpg", jpeg())]))
    row = await imp.reload(job)
    assert (status, row.status, _errors(row)) == ("failed", JobStatus.FAILED, ["invalid_archive"])


# --- 4. delete aborts the upload -------------------------------------------------


async def _session(imp, job_id) -> UploadSession:
    async with imp.pipe.db_state.session_factory() as s:
        row = await s.get(ImportJob, job_id)
        return await s.get(UploadSession, row.upload_session_id)


async def test_delete_aborts_the_upload_session_and_its_parts(imp):
    job_id, ticket = await upload_zip(imp, make_zip([("a.jpg", jpeg())]))
    session_id = (await _session(imp, job_id)).id
    await controls.delete_job(imp.runtime, DEFAULT_TENANT, job_id)
    async with imp.pipe.db_state.session_factory() as s:
        found = await s.get(UploadSession, session_id)
    assert found.status is UploadStatus.ABORTED and found.cleaned_at is not None
    with pytest.raises(StorageNotFoundError):  # the parts are gone with the multipart upload
        await imp.pipe.backend.list_parts(ticket.key, ticket.upload)


async def test_delete_waits_for_a_seal_holding_the_upload(imp):
    job_id, _ = await upload_zip(imp, make_zip([("a.jpg", jpeg())]))
    sid = (await _session(imp, job_id)).id
    async with imp.pipe.db_state.session_factory() as s:
        values = {"status": UploadStatus.COMPLETING}
        await s.execute(update(UploadSession).where(UploadSession.id == sid).values(**values))
        await s.commit()
    with pytest.raises(Conflict):
        await controls.delete_job(imp.runtime, DEFAULT_TENANT, job_id)
    assert (await imp.reload(SimpleNamespace(id=job_id))).status is JobStatus.UPLOADING


async def test_a_seal_after_delete_finds_nothing(imp):
    job_id, _ = await upload_zip(imp, make_zip([("a.jpg", jpeg())]))
    await controls.delete_job(imp.runtime, DEFAULT_TENANT, job_id)
    with pytest.raises(NotFound):
        await zip_upload.seal(imp.runtime, DEFAULT_TENANT, job_id, {})


# --- 5 + 6. external_source and manual coordinates -------------------------------


async def test_metadata_external_source_and_manual_location(imp):
    meta = {
        "a.jpg": {"external_id": "7", "external_source": "lucas", "lat": 1.0, "lng": 2.0},
        "b.jpg": {"external_id": "7", "external_source": "other"},
        "c.jpg": {"external_id": "7"},
    }
    members = [
        ("metadata.json", json.dumps(meta).encode()),
        ("a.jpg", jpeg((8, 6), "red")),
        ("b.jpg", jpeg((8, 6), "blue")),
        ("c.jpg", jpeg((8, 6), "green")),
    ]
    job, status = await import_zip(imp, make_zip(members))
    assert status == "completed"
    by_name = {i.filename: i for i in await imp.images()}
    assert {n: i.external_source for n, i in by_name.items()} == {
        "a.jpg": "lucas",
        "b.jpg": "other",
        "c.jpg": constants.SOURCE_IMPORT,
    }
    assert by_name["a.jpg"].location_source == LocationSource.MANUAL
    assert await imp.counts(job) == ("completed", 3, 3, 3, 0, 0)

    again, _ = await import_zip(imp, make_zip(members))  # every source dedupes on its own
    assert await imp.counts(again) == ("completed", 3, 3, 0, 3, 0)


async def test_an_overlong_external_source_is_invalid(imp):
    meta = {"a.jpg": {"external_source": "x" * (constants.EXTERNAL_SOURCE_MAX + 1)}}
    data = make_zip([("metadata.json", json.dumps(meta).encode()), ("a.jpg", jpeg())])
    job, _ = await import_zip(imp, data)
    assert _errors(await imp.reload(job)) == ["metadata_invalid"]


# --- 7. the part size is the session's ------------------------------------------


async def test_the_seal_uses_the_part_size_the_upload_was_opened_with(imp, monkeypatch):
    data = make_zip([(f"{c}.jpg", jpeg((16, 12), c)) for c in ("red", "blue", "green")])
    monkeypatch.setattr(constants, "DIRECT_PART_BYTES", 400)
    job_id, ticket = await upload_zip(imp, data)
    assert ticket.parts > 1 and (await _session(imp, job_id)).part_size == 400
    monkeypatch.setattr(constants, "DIRECT_PART_BYTES", 1000)  # a deploy in between
    generation = await zip_upload.seal(imp.runtime, DEFAULT_TENANT, job_id, {})
    job = SimpleNamespace(id=job_id)
    assert await zip_import.import_zip_async(imp.runtime, DEFAULT_TENANT, job_id, generation) == (
        "completed"
    )
    assert (await imp.reload(job)).done_count == 3


# --- 8. a store whose head has an etag ------------------------------------------


async def test_etag_store_seal_and_download(imp, tmp_path):
    data = make_zip([("a.jpg", jpeg())])
    store = EtagStore(imp.pipe.store)
    runtime = SimpleNamespace(store=lambda: store, settings=lambda: imp.pipe.settings)
    _, ticket = await upload_zip(imp, data)
    await imp.pipe.backend.complete_multipart(
        ticket.key, ticket.upload, await imp.pipe.backend.list_parts(ticket.key, ticket.upload)
    )
    size, fingerprint = await zip_upload._measure(runtime, ticket, [])
    assert size == len(data) and not fingerprint.startswith(('"', "md5parts:", "sha256:"))

    dest = tmp_path / "copy.zip"
    await fetch_verified(store, ticket.key, fingerprint=fingerprint, size=size, dest=dest)
    assert dest.read_bytes() == data
    with pytest.raises(ZipRejected) as err:
        await fetch_verified(store, ticket.key, fingerprint="other", size=size, dest=dest)
    assert err.value.code == "archive_changed"

    swapped = data[:-1] + bytes([data[-1] ^ 1])

    async def replace():
        await imp.pipe.store.put(ticket.key, swapped, content_type="application/zip", size=size)

    racing = EtagStore(imp.pipe.store, on_stream=replace)
    with pytest.raises(ZipRejected) as err:
        await fetch_verified(racing, ticket.key, fingerprint=fingerprint, size=size, dest=dest)
    assert err.value.code == "archive_changed"


# --- 9. named limits ------------------------------------------------------------


async def test_the_extract_body_shares_the_direct_upload_part_limit():
    from sm_images.schemas.imports import ZipExtract

    limit = ZipExtract.model_fields["parts"].metadata
    assert any(getattr(m, "max_length", None) == constants.DIRECT_MAX_PARTS for m in limit)
    assert zip_safety.READ_CHUNK_BYTES and zip_import.ENTRY_BATCH


async def test_sealed_rows_carry_size_and_fingerprint(imp):
    job, _ = await sealed_zip(imp, make_zip([("a.jpg", jpeg())]))
    async with imp.pipe.db_state.session_factory() as s:
        row = (await s.execute(select(ImportJob).where(ImportJob.id == job.id))).scalar_one()
    assert row.source_size and row.source_etag.startswith("md5parts:")
