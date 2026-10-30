"""Task 18 review fixes, round 3: dates that overflow in UTC are no date, and
a job that reconcile keeps relaunching without progress is failed as stalled."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.ingest.imports import chunk, recover, values
from sm_images.models import ImportJob
from sm_images.models.enums import JobStatus
from sqlalchemy import update

from tests.support.imports import b64, feature
from tests.support.pipeline import jpeg
from tests.support.zip import import_zip, make_zip

pytestmark = pytest.mark.asyncio
EDGES = ("0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00")


async def test_dates_whose_utc_overflows_are_no_date():
    for raw in EDGES:
        assert values.parse_datetime(raw) is None, raw
    got = values.parse_datetime("2024-05-01T12:00:00+02:00")
    assert got == datetime(2024, 5, 1, 10, tzinfo=UTC) and got.utcoffset() == timedelta(0)


async def test_an_overflowing_date_in_zip_metadata(imp):
    meta = {"a.jpg": {"captured_at": EDGES[0]}, "b.jpg": {"captured_at": EDGES[1]}}
    members = [
        ("metadata.json", json.dumps(meta).encode()),
        ("a.jpg", jpeg((8, 6), "red")),
        ("b.jpg", jpeg((8, 6), "blue")),
    ]
    _, status = await import_zip(imp, make_zip(members))
    assert status == "completed"
    assert [i.captured_at for i in await imp.images()] == [None, None]


async def test_an_overflowing_date_in_geojson(imp):
    feats = [feature({"img": b64("red"), "t": EDGES[0]}), feature({"img": b64(), "t": EDGES[1]})]
    job = await imp.job(feats, image_prop="img", datetime_prop="t")
    assert await imp.run(job) == "completed"
    assert [i.captured_at for i in await imp.images()] == [None, None]


# --- the poison-job breaker -----------------------------------------------------


async def _stale(imp, job, **values) -> None:
    async with imp.pipe.db_state.session_factory() as s:
        old = datetime.now(UTC) - timedelta(hours=1)
        stmt = update(ImportJob).where(ImportJob.id == job.id).values(heartbeat_at=old, **values)
        await s.execute(stmt)
        await s.commit()


async def _reconcile(imp) -> None:
    await recover.recover_imports(
        imp.runtime, DEFAULT_TENANT, datetime.now(UTC) - timedelta(1 / 24 / 2)
    )


def _poison(monkeypatch) -> dict:
    calls = {"n": 0}

    async def broken(*a, **k):
        calls["n"] += 1
        raise RuntimeError("an error nobody anticipated")

    monkeypatch.setattr(chunk, "record_chunk", broken)
    return calls


async def test_a_job_relaunched_without_progress_ends_stalled(imp, monkeypatch):
    calls = _poison(monkeypatch)
    job = await imp.job([feature({"img": b64()})])
    with pytest.raises(RuntimeError):
        await imp.run(job)
    for _ in range(recover.RELAUNCH_LIMIT):
        await _stale(imp, job)
        await _reconcile(imp)
        assert (await imp.reload(job)).status is JobStatus.RUNNING
    assert calls["n"] == 1 + recover.RELAUNCH_LIMIT
    await _stale(imp, job)
    await _reconcile(imp)
    row = await imp.reload(job)
    assert (row.status, [e["code"] for e in row.errors]) == (JobStatus.FAILED, ["stalled"])
    assert calls["n"] == 1 + recover.RELAUNCH_LIMIT  # not launched again
    await _stale(imp, job)
    await _reconcile(imp)  # terminal: reconcile leaves it alone
    assert (await imp.reload(job)).status is JobStatus.FAILED


async def test_progress_resets_the_relaunch_count(imp, monkeypatch):
    _poison(monkeypatch)
    job = await imp.job([feature({"img": b64()})])
    with pytest.raises(RuntimeError):
        await imp.run(job)
    for n in range(2 * recover.RELAUNCH_LIMIT):
        await _stale(imp, job, done_count=n + 1)  # some progress every time
        await _reconcile(imp)
    row = await imp.reload(job)
    assert row.status is JobStatus.RUNNING and row.relaunches == 1


async def test_a_resume_resets_the_relaunch_count(imp, monkeypatch):
    from sm_images.ingest.imports import controls

    _poison(monkeypatch)
    job = await imp.job([feature({"img": b64()})])
    with pytest.raises(RuntimeError):
        await imp.run(job)
    for _ in range(3):
        await _stale(imp, job)
        await _reconcile(imp)
    assert (await imp.reload(job)).relaunches == 3
    await controls.pause(imp.runtime, DEFAULT_TENANT, job.id)
    with pytest.raises(RuntimeError):
        await controls.resume(imp.runtime, DEFAULT_TENANT, job.id)  # an operator retries
    assert (await imp.reload(job)).relaunches == 0
