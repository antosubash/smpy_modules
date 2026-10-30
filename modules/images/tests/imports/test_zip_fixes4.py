"""Task 18 review fixes, round 4: the poison-job breaker counts every kind of
progress, and a healthy slow download is never reclaimed as stale."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sm_images.core import constants
from sm_images.imports import beat, chunk, download, launch, recover, reset, retrying
from sm_images.jobs.reconcile import CUTOFF
from sm_images.models import ImportJob
from sm_images.models.enums import JobStatus
from sm_images.settings import ImagesSettings
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import update

from tests.support.imports import HOST, URL, feature
from tests.support.pipeline import jpeg

pytestmark = pytest.mark.asyncio


async def _stale(imp, job, **values) -> None:
    async with imp.pipe.db_state.session_factory() as s:
        old = datetime.now(UTC) - timedelta(hours=1)
        stmt = update(ImportJob).where(ImportJob.id == job.id).values(heartbeat_at=old, **values)
        await s.execute(stmt)
        await s.commit()


async def _reconcile(imp, cutoff: datetime | None = None) -> None:
    cutoff = cutoff or datetime.now(UTC) - timedelta(minutes=30)
    await recover.recover_imports(imp.runtime, DEFAULT_TENANT, cutoff)


@pytest.fixture
def poisoned(monkeypatch):
    async def broken(*a, **k):
        raise RuntimeError("an error nobody anticipated")

    monkeypatch.setattr(chunk, "record_chunk", broken)


async def _poisoned_job(imp):
    job = await imp.job([feature({"img": "x"})])
    with pytest.raises(RuntimeError):
        await imp.run(job)
    return job


# --- 1. every settlement and every reset batch is progress -----------------------


@pytest.mark.parametrize("counter", ["failed_count", "duplicate_count"])
async def test_settling_only_failures_or_duplicates_never_trips(imp, poisoned, counter):
    job = await _poisoned_job(imp)
    for n in range(2 * recover.RELAUNCH_LIMIT):
        await _stale(imp, job, **{counter: n + 1})  # one more settled each time
        await _reconcile(imp)
    row = await imp.reload(job)
    assert row.status is JobStatus.RUNNING and row.relaunches == 1


async def test_reset_batches_are_progress(imp, poisoned):
    job = await _poisoned_job(imp)
    for n in range(2 * recover.RELAUNCH_LIMIT):
        await _stale(imp, job, reset_progress=n + 1)
        await _reconcile(imp)
    row = await imp.reload(job)
    assert row.status is JobStatus.RUNNING and row.relaunches == 1


async def test_a_reset_batch_counts_the_rows_it_changed(imp, monkeypatch):
    monkeypatch.setattr(launch, "launch_downloads", _record([]))
    job = await imp.job([feature({"nope": 1}), feature({"nope": 2})], URL)
    assert await imp.run(job) == "completed"  # both items failed
    async with imp.pipe.db_state.session_factory() as s:
        values = {"status": JobStatus.RESETTING, "reset_mode": reset.MODE_RESTART}
        await s.execute(update(ImportJob).where(ImportJob.id == job.id).values(**values))
        await s.commit()
    row = await imp.reload(job)
    assert await reset.reset_batch(imp.runtime, DEFAULT_TENANT, job.id, row.generation) == 2
    assert (await imp.reload(job)).reset_progress == 2


# --- 2. a slow download heartbeats its job ---------------------------------------


def _record(sent: list):
    async def fake(runtime, tenant, job_id, generation, ids):
        sent.append(list(ids))

    return fake


async def test_a_slow_download_heartbeats_and_is_not_reclaimed(file_imp, monkeypatch):
    imp = file_imp  # the beat and the download write from sessions of their own
    sent: list[list[int]] = []
    monkeypatch.setattr(launch, "launch_downloads", _record(sent))
    monkeypatch.setattr(beat, "HEARTBEAT_SECONDS", 0.05)

    release = asyncio.Event()

    async def slow(url, limiter, settings, prior, *, before):
        await before()  # the item is claimed in its slot, then the fetch stalls
        await release.wait()  # held until the test has seen the heartbeat renewed
        return jpeg((8, 6), "blue"), 1

    monkeypatch.setattr(download, "fetch_with_retries", slow)
    job = await imp.job([feature({"url": f"https://{HOST}/a.jpg"})], URL)
    await imp.run(job)
    row = await imp.reload(job)
    assert row.status is JobStatus.RUNNING and sent
    await _stale(imp, job)  # the runner is done; only the download is left
    task = asyncio.create_task(
        download.download_items_async(imp.runtime, DEFAULT_TENANT, job.id, row.generation, sent[0])
    )
    horizon = datetime.now(UTC) - timedelta(seconds=30)
    for _ in range(400):  # event-driven: until the beat has renewed the 1h-old heartbeat
        beating = (await imp.reload(job)).heartbeat_at
        if beating is not None and beating.replace(tzinfo=UTC) > horizon:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("the heartbeat was never renewed")
    await _reconcile(imp, horizon)  # a download still held: a stale job would be reclaimed
    release.set()
    assert await task == 1
    after = await imp.reload(job)
    assert after.generation == row.generation  # never reclaimed
    assert (after.status, after.done_count) == (JobStatus.COMPLETED, 1)


async def test_download_timeout_stays_under_the_stale_cutoff():
    top = constants.DOWNLOAD_TIMEOUT_MAX
    assert ImagesSettings(download_timeout=top).download_timeout == top
    with pytest.raises(ValidationError):
        ImagesSettings(download_timeout=top + 1)
    margin = 60
    assert top + margin <= CUTOFF.total_seconds()
    # ...and one item's worst case fits inside its claim.
    worst = retrying.INLINE_ATTEMPTS * top + (retrying.INLINE_ATTEMPTS - 1) * (
        retrying.INLINE_WAIT_SECONDS
    )
    assert worst < download.CLAIM_SECONDS
