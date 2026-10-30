"""Job controls: pause, resume, restart, retry-failed, delete.

Every control is one compare-and-set on the job row, committed **before** any
work is handed on, so a double click or a concurrent control loses cleanly:

* **pause** - an active job stops at its runner's next write, and in-flight
  settlements roll back (they are fenced on ``running``).
* **resume** - a paused job, or an active one whose runner went silent, gets a
  new generation and a new runner; the runner hands out pending URL items.
* **restart** and **retry-failed** - the job moves to ``resetting`` with a new
  generation and a ``reset_mode`` in that one commit, then :mod:`.reset`
  resets items in fenced, resumable batches and launches the runner. Restart
  needs the source - staged, or a URL to fetch it from again - except for a
  finished URL job, which restarts from its rows. Retry-failed on a base64 job
  needs its source still staged (a finished base64 job with failures keeps it
  until the janitor's grace period, :mod:`.terminal`).
* **delete** - :func:`sm_images.ingest.imports.cleanup.delete_job`.

The compare-and-set also names the job's current source: a terminal job's
clean-up that detached it first makes the control lose (409) rather than
restart a job whose source was just deleted.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Final

from sqlalchemy import func, or_, select, update

from sm_images.ingest.imports import jobs
from sm_images.ingest.imports import launch as handoff
from sm_images.ingest.imports.cleanup import delete_job
from sm_images.ingest.imports.features import PARSE_CODES
from sm_images.ingest.imports.jobs import ACTIVE, now, where
from sm_images.ingest.imports.lookup import conflict, get
from sm_images.ingest.imports.reset import MODE_RESTART, MODE_RETRY, MODE_ROWS
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import ImportKind, ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime

__all__ = ["STALE_AFTER", "delete_job", "get", "pause", "restart", "resume", "retry_failed"]

STALE_AFTER: Final = timedelta(minutes=5)
"""A runner silent for this long may be replaced by a resume (as reconcile does)."""


async def _cas(runtime: Runtime, tenant: str, job_id: uuid.UUID, conds: list, values: dict) -> Any:
    stmt = (
        update(ImportJob)
        .where(*where(tenant, job_id), *conds)
        .values(**values, updated_at=now())
        .returning(ImportJob.generation)
    )
    return await jobs.returning_one(runtime, stmt)


Actor = tuple[str, str] | None
"""``(user id, access basis)`` of whoever used a control that reopens a job: it
runs under their right from then on (``imports.access``)."""


def _as(actor: Actor) -> dict[str, Any]:
    return {} if actor is None else {"run_as": actor[0], "access_basis": actor[1]}


def _unchanged(row: ImportJob) -> list[Any]:
    same_source = (
        ImportJob.source_key.is_(None)
        if row.source_key is None
        else ImportJob.source_key == row.source_key
    )
    return [ImportJob.generation == row.generation, same_source]


async def pause(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> ImportJob:
    paused = {"status": JobStatus.PAUSED}
    found = await _cas(runtime, tenant, job_id, [ImportJob.status.in_(ACTIVE)], paused)
    if found is None:
        await get(runtime, tenant, job_id)
        raise conflict("job_not_active", "Only a running import can be paused")
    return await get(runtime, tenant, job_id)


async def resume(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, *, launch: bool = True, actor: Actor = None
) -> ImportJob:
    silent = ImportJob.heartbeat_at.is_(None) | (ImportJob.heartbeat_at < now() - STALE_AFTER)
    resumable = (ImportJob.status == JobStatus.PAUSED) | (ImportJob.status.in_(ACTIVE) & silent)
    values = {
        "status": JobStatus.PENDING,
        "generation": ImportJob.generation + 1,
        "heartbeat_at": now(),
        "relaunches": 0,
        **_as(actor),
    }
    found = await _cas(runtime, tenant, job_id, [resumable], values)
    if found is None:
        await get(runtime, tenant, job_id)
        raise conflict("job_not_resumable", "This import is not paused or stalled")
    if launch:
        await handoff.launch_runner(runtime, tenant, job_id, int(found[0]))
    return await get(runtime, tenant, job_id)


async def _enter_reset(
    runtime: Runtime,
    tenant: str,
    row: ImportJob,
    mode: str,
    extra: dict,
    launch: bool,
    actor: Actor = None,
) -> ImportJob:
    values = {
        "status": JobStatus.RESETTING,
        "reset_mode": mode,
        "generation": ImportJob.generation + 1,
        "errors": [],
        "heartbeat_at": now(),
        "relaunches": 0,
        **extra,
        **_as(actor),
    }
    found = await _cas(runtime, tenant, row.id, _unchanged(row), values)
    if found is None:
        raise conflict("job_changed", "The import changed meanwhile; try again")
    if launch:
        await handoff.launch_reset(runtime, tenant, row.id, int(found[0]))
    return await get(runtime, tenant, row.id)


def job_errors(row: ImportJob, *, keep_parse: bool = False) -> list[dict[str, Any]]:
    """``row``'s errors without the failed rows' (``item_errors``) - except, with
    ``keep_parse``, the rows the parser refused: a retry (or a restart from the
    recorded rows) leaves those failed and never records them again."""
    return [
        e
        for e in row.errors or []
        if "item" not in e or (keep_parse and e.get("code") in PARSE_CODES)
    ]


def _recorded(row: ImportJob) -> bool:
    return row.total_count > 0 and row.checkpoint_index >= row.total_count


async def restart(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, *, launch: bool = True, actor: Actor = None
) -> ImportJob:
    row = await get(runtime, tenant, job_id)
    zero = {"done_count": 0, "duplicate_count": 0, "failed_count": 0}
    if row.source_key is None and row.source_url is None:
        if row.kind is ImportKind.GEOJSON_URL and _recorded(row):
            kept = {"errors": job_errors(row, keep_parse=True)}
            return await _enter_reset(runtime, tenant, row, MODE_ROWS, kept, launch, actor)
        raise conflict("source_gone", "The source of this import is no longer stored")
    extra: dict[str, Any] = {**zero, "checkpoint_index": 0, "errors": job_errors(row)}
    if row.source_key is None:
        extra["total_count"] = 0  # re-staged from its URL, and counted again
    return await _enter_reset(runtime, tenant, row, MODE_RESTART, extra, launch, actor)


async def _retryable(runtime: Runtime, tenant: str, row: ImportJob) -> int:
    stmt = select(func.count()).where(
        ImportItem.job_id == row.id,
        ImportItem.tenant_id == tenant,
        ImportItem.status == ItemStatus.FAILED,
        or_(ImportItem.last_error.is_(None), ImportItem.last_error.not_in(PARSE_CODES)),
    )
    if row.kind is ImportKind.GEOJSON_URL:
        stmt = stmt.where(ImportItem.url.is_not(None))
    async with runtime.session_factory() as db:
        n = (await db.execute(stmt)).scalar_one()
        await db.rollback()
    return int(n)


async def retry_failed(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, *, launch: bool = True, actor: Actor = None
) -> ImportJob:
    row = await get(runtime, tenant, job_id)
    url = row.kind is ImportKind.GEOJSON_URL
    if row.status in (JobStatus.PAUSED, JobStatus.RESETTING):
        raise conflict("job_paused", "Resume the import before retrying its failures")
    if not url and row.source_key is None:
        raise conflict("source_gone", "The source of this import is no longer stored")
    if url and row.status not in ACTIVE and not _recorded(row):
        raise conflict("job_incomplete", "This import never finished reading its source")
    if not await _retryable(runtime, tenant, row):
        return row
    extra = {"errors": job_errors(row, keep_parse=True)}  # retried rows say why again
    return await _enter_reset(runtime, tenant, row, MODE_RETRY, extra, launch, actor)
