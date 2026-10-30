"""ZIP imports resume, pause, restart and recover like GeoJSON ones: every entry
is an item at its archive index, and every write is fenced on the generation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_images.imports import claims, controls, recover, settle, zip_import
from sm_images.models import ImportJob, UploadSession
from sm_images.models.enums import JobStatus
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import update

from tests.imports.test_import_runner import Killed, kill_after
from tests.support.pipeline import jpeg
from tests.support.zip import import_zip, make_zip, run_zip, sealed_zip, upload_zip

pytestmark = pytest.mark.asyncio
COLORS = ("red", "blue", "green", "white", "black")


def _five() -> bytes:
    return make_zip([(f"{c}.jpg", jpeg((8, 6), c)) for c in COLORS])


async def _set(imp, model, row_id, **values) -> None:
    async with imp.pipe.db_state.session_factory() as s:
        await s.execute(update(model).where(model.id == row_id).values(**values))
        await s.commit()


async def test_zip_resume_after_kill_no_duplicates(imp, monkeypatch):
    """Killed after three ingests (the second chunk recorded): the replay skips
    what has an image and finds the rest by index - no duplicate, exact counts."""
    monkeypatch.setattr(zip_import, "ENTRY_BATCH", 2)
    job, generation = await sealed_zip(imp, _five())
    kill_after(monkeypatch, settle, "ingest_item", 3)
    with pytest.raises(Killed):
        await run_zip(imp, job, generation)
    assert len(await imp.images()) == 3
    status, total, checkpoint, done, _, _ = await imp.counts(job)
    assert (status, total, checkpoint, done) == ("running", 5, 4, 3)

    monkeypatch.undo()
    monkeypatch.setattr(zip_import, "ENTRY_BATCH", 2)
    calls = kill_after(monkeypatch, settle, "ingest_item", 100)
    claimed = await claims.claim_stale(imp.runtime, DEFAULT_TENANT, job.id)
    assert await run_zip(imp, job, generation) == "stale"  # the old generation writes nothing
    assert await run_zip(imp, job, claimed) == "completed"
    assert calls["n"] == 2
    assert await imp.counts(job) == ("completed", 5, 5, 5, 0, 0)
    ids = [i.image_id for i in await imp.items(job)]
    assert None not in ids and len(set(ids)) == 5 and len(await imp.images()) == 5


async def test_pause_stops_extraction_at_the_next_entry(imp, monkeypatch):
    job, generation = await sealed_zip(imp, _five())
    real, calls = settle.ingest_item, {"n": 0}

    async def pausing(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            await controls.pause(imp.runtime, DEFAULT_TENANT, job.id)
        return await real(*args, **kwargs)

    monkeypatch.setattr(settle, "ingest_item", pausing)
    assert await run_zip(imp, job, generation) == "stopped"
    assert calls["n"] == 2 and len(await imp.images()) == 1  # the second rolled back
    monkeypatch.undo()
    row = await controls.resume(imp.runtime, DEFAULT_TENANT, job.id)  # eager: runs it
    assert row.status is JobStatus.COMPLETED
    assert len(await imp.images()) == 5


async def test_retry_and_restart_run_the_zip_runner(imp):
    data = make_zip([("a.jpg", jpeg((8, 6), "red")), ("notes.txt", b"text")])
    job, _ = await import_zip(imp, data)
    assert await imp.counts(job) == ("completed", 2, 2, 1, 0, 1)
    row = await controls.retry_failed(imp.runtime, DEFAULT_TENANT, job.id)
    assert (row.status, row.failed_count, row.done_count) == (JobStatus.COMPLETED, 1, 1)
    row = await controls.restart(imp.runtime, DEFAULT_TENANT, job.id)
    assert (row.status, row.failed_count, row.done_count) == (JobStatus.COMPLETED, 1, 1)
    assert len(await imp.images()) == 1


async def test_reconcile_relaunches_a_sealed_job_whose_runner_was_lost(imp):
    job, _ = await sealed_zip(imp, _five())
    old = datetime.now(UTC) - timedelta(hours=1)
    await _set(imp, ImportJob, job.id, heartbeat_at=old)
    relaunched, _ = await recover.recover_imports(imp.runtime, DEFAULT_TENANT, old + timedelta(1))
    assert relaunched == 1
    assert (await imp.reload(job)).status is JobStatus.COMPLETED
    assert len(await imp.images()) == 5


async def test_an_upload_that_never_arrives_is_failed_by_reconcile_not_relaunched(imp):
    job_id, ticket = await upload_zip(imp, _five())

    class J:
        id = job_id

    future = datetime.now(UTC) + timedelta(hours=1)
    await _set(imp, ImportJob, job_id, heartbeat_at=datetime.now(UTC) - timedelta(days=1))
    assert await recover.recover_imports(imp.runtime, DEFAULT_TENANT, future) == (0, 0)
    assert (await imp.reload(J)).status is JobStatus.UPLOADING  # still uploading: no runner

    session_id = (await imp.reload(J)).upload_session_id
    await _set(imp, UploadSession, session_id, expires_at=datetime.now(UTC) - timedelta(1))
    assert await recover.expire_uploads(imp.runtime, DEFAULT_TENANT) == 1
    row = await imp.reload(J)
    assert (row.status, [e["code"] for e in row.errors]) == (JobStatus.FAILED, ["upload_expired"])
    assert row.staged_keys == [] and ticket.key not in imp.stored()
    assert await recover.expire_uploads(imp.runtime, DEFAULT_TENANT) == 0


async def test_controls_refuse_an_uploading_job_and_delete_removes_it(imp):
    from sm_images.core.errors import Conflict

    job_id, _ = await upload_zip(imp, _five())
    for control in (controls.pause, controls.resume, controls.restart, controls.retry_failed):
        with pytest.raises(Conflict):
            await control(imp.runtime, DEFAULT_TENANT, job_id)
    await controls.delete_job(imp.runtime, DEFAULT_TENANT, job_id)
    async with imp.pipe.db_state.session_factory() as s:
        assert await s.get(ImportJob, job_id) is None
