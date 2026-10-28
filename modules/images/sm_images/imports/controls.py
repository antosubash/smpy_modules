"""Job controls: pause, resume, restart, retry-failed, delete.

Every control is a compare-and-set on the job row, committed **before** any
work is handed on, so a double click or a concurrent control loses cleanly:

* **pause** - an active job stops at the runner's next write; downloads still
  queued leave their items ``pending``.
* **resume** - a paused job, or an active one whose runner went silent, gets a
  new generation and a new runner (an old runner, if alive, stops at its next
  write); pending URL items are handed out again.
* **restart** - a new generation, checkpoint and counters reset, then every
  item that did not produce an image is deleted, :data:`RESET_CHUNK` at a time
  (short transactions, set-based); the completed ones stay and are counted
  back in, so their images are not fetched or ingested again. That needs the
  source - staged, or a URL to fetch it from again. A finished URL job whose
  staged source is gone (a terminal job deletes it) still restarts from its
  rows, which carry every URL: its failed items go back to ``pending`` and the
  counters are recounted.
* **retry-failed** - ``failed`` items back to ``pending`` (once each, in
  chunks), the failed counter decremented by exactly as many and the job
  reopened; then the items are handed out (URL) or the runner re-streams the
  source for them (base64, which needs the source still staged).
* **delete** - fence, then remove the job, its items and its staged objects
  (behind intents, so a failed object delete is still reaped by the janitor).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Final

from simple_module_db import finalize_session
from sqlalchemy import delete, func, select, update

from sm_images.imports import jobs, terminal
from sm_images.imports import launch as handoff
from sm_images.imports.cleanup import delete_job
from sm_images.imports.jobs import ACTIVE, now, where
from sm_images.imports.lookup import conflict, get
from sm_images.imports.retry import RESET_CHUNK, pending_url_items, reset_failed, retry_failed
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import ImportKind, ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime

__all__ = [
    "RESET_CHUNK",
    "STALE_AFTER",
    "conflict",
    "delete_job",
    "get",
    "pause",
    "pending_url_items",
    "restart",
    "resume",
    "retry_failed",
]

STALE_AFTER: Final = timedelta(minutes=5)
"""A runner silent for this long may be replaced by a resume (as reconcile does)."""
_SYNC: Final = {"synchronize_session": False}


async def _cas(runtime: Runtime, tenant: str, job_id: uuid.UUID, conds: list, values: dict) -> Any:
    stmt = (
        update(ImportJob)
        .where(*where(tenant, job_id), *conds)
        .values(**values, updated_at=now())
        .returning(ImportJob.generation)
    )
    return await jobs.returning_one(runtime, stmt)


async def pause(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> ImportJob:
    paused = {"status": JobStatus.PAUSED}
    found = await _cas(runtime, tenant, job_id, [ImportJob.status.in_(ACTIVE)], paused)
    if found is None:
        await get(runtime, tenant, job_id)
        raise conflict("job_not_active", "Only a running import can be paused")
    return await get(runtime, tenant, job_id)


async def resume(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, *, launch: bool = True
) -> ImportJob:
    silent = (ImportJob.heartbeat_at.is_(None)) | (ImportJob.heartbeat_at < now() - STALE_AFTER)
    resumable = (ImportJob.status == JobStatus.PAUSED) | (ImportJob.status.in_(ACTIVE) & silent)
    values = {
        "status": JobStatus.PENDING,
        "generation": ImportJob.generation + 1,
        "heartbeat_at": now(),
    }
    found = await _cas(runtime, tenant, job_id, [resumable], values)
    if found is None:
        await get(runtime, tenant, job_id)
        raise conflict("job_not_resumable", "This import is not paused or stalled")
    row = await get(runtime, tenant, job_id)
    if launch:
        await handoff.launch_runner(runtime, tenant, job_id, int(found[0]))
        if row.kind is ImportKind.GEOJSON_URL:
            await pending_url_items(runtime, tenant, job_id)
        row = await get(runtime, tenant, job_id)
    return row


async def _delete_unfinished(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> None:
    while True:
        page = (
            select(ImportItem.id)
            .where(
                ImportItem.job_id == job_id,
                ImportItem.tenant_id == tenant,
                ImportItem.status != ItemStatus.DONE,
            )
            .limit(RESET_CHUNK)
        )
        async with runtime.session_factory() as db:
            ids = list((await db.execute(page)).scalars())
            if ids:
                await db.execute(
                    delete(ImportItem)
                    .where(ImportItem.id.in_(ids), ImportItem.tenant_id == tenant)
                    .execution_options(**_SYNC)
                )
            await finalize_session(db)
        if len(ids) < RESET_CHUNK:
            return


async def _recount(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> None:
    stmt = (
        select(ImportItem.status, func.count())
        .where(ImportItem.job_id == job_id, ImportItem.tenant_id == tenant)
        .group_by(ImportItem.status)
    )
    async with runtime.session_factory() as db:
        counts = dict((await db.execute(stmt)).tuples().all())
        values = {name: counts.get(status, 0) for status, name in jobs.COUNTERS.items()}
        seed = update(ImportJob).where(*where(tenant, job_id)).values(**values)
        await db.execute(seed.execution_options(**_SYNC))
        await finalize_session(db)


async def _restart_from_rows(
    runtime: Runtime, tenant: str, row: ImportJob, launch: bool
) -> ImportJob:
    values = {
        "status": JobStatus.RUNNING,
        "generation": ImportJob.generation + 1,
        "errors": [],
        "heartbeat_at": now(),
    }
    found = await _cas(runtime, tenant, row.id, [ImportJob.generation == row.generation], values)
    if found is None:
        raise conflict("job_changed", "The import changed meanwhile; try again")
    reset = await reset_failed(runtime, tenant, row.id, url=True, count=False)
    await _recount(runtime, tenant, row.id)
    if launch and reset:
        await handoff.launch_downloads(runtime, tenant, row.id, reset)
    if launch:
        await terminal.try_complete(runtime, tenant, row.id)
    return await get(runtime, tenant, row.id)


async def restart(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, *, launch: bool = True
) -> ImportJob:
    row = await get(runtime, tenant, job_id)
    if row.source_key is None and row.source_url is None:
        recorded = row.total_count > 0 and row.checkpoint_index >= row.total_count
        if row.kind is ImportKind.GEOJSON_URL and recorded:
            return await _restart_from_rows(runtime, tenant, row, launch)
        raise conflict("source_gone", "The source of this import is no longer stored")
    values = {
        "status": JobStatus.PENDING if row.source_key else JobStatus.STAGING,
        "generation": ImportJob.generation + 1,
        "checkpoint_index": 0,
        "done_count": 0,
        "duplicate_count": 0,
        "failed_count": 0,
        "errors": [],
        "heartbeat_at": now(),
    }
    found = await _cas(runtime, tenant, job_id, [ImportJob.generation == row.generation], values)
    if found is None:
        raise conflict("job_changed", "The import changed meanwhile; try again")
    await _delete_unfinished(runtime, tenant, job_id)
    done = select(func.count()).where(
        ImportItem.job_id == job_id,
        ImportItem.tenant_id == tenant,
        ImportItem.status == ItemStatus.DONE,
    )
    async with runtime.session_factory() as db:
        seeded = (await db.execute(done)).scalar_one()
        seed = update(ImportJob).where(*where(tenant, job_id)).values(done_count=seeded)
        await db.execute(seed.execution_options(**_SYNC))
        await finalize_session(db)
    if launch:
        await handoff.launch_runner(runtime, tenant, job_id, int(found[0]))
    return await get(runtime, tenant, job_id)
