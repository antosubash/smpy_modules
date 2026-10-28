"""The import job's record: creation, the generation fence, counters.

Every write that a runner or a download makes to a job is a conditional
``UPDATE``, never a read-modify-write of a loaded row:

* **the generation fence** - a runner holds ``generation``; a restart, a
  resume and reconcile's reclaim bump it, so a runner from before stops at its
  next write (:func:`start`, :func:`heartbeat`, ``chunk.advance_checkpoint``);
* **counters** are increments (``done_count + n``, :func:`bump`), so
  concurrent downloads never lose one another's.

Completion and the other terminal moves are in :mod:`.terminal`.

Every statement names the tenant explicitly (Core ``UPDATE`` is invisible to
the ORM tenancy guard).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from simple_module_db import finalize_session
from sqlalchemy import case, func, select, update

from sm_images.imports.mapping import Mapping
from sm_images.intents import clear_intents
from sm_images.models import Collection, ImportItem, ImportJob
from sm_images.models.enums import ImportKind, ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime

__all__ = [
    "ACTIVE",
    "COUNTERS",
    "TERMINAL",
    "JobSnap",
    "bump",
    "claim_stale",
    "create_job",
    "heartbeat",
    "live_collection",
    "load",
    "now",
    "pending_count",
    "resume_index",
    "returning_one",
    "snapshot",
    "start",
    "touch",
    "where",
]

ACTIVE: Final = (JobStatus.PENDING, JobStatus.STAGING, JobStatus.RUNNING)
TERMINAL: Final = (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
COUNTERS: Final = {
    ItemStatus.DONE: "done_count",
    ItemStatus.DUPLICATE: "duplicate_count",
    ItemStatus.FAILED: "failed_count",
}
_SYNC: Final = {"synchronize_session": False}


def now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class JobSnap:
    """Plain values of a job, safe to hold across sessions."""

    id: uuid.UUID
    collection_id: uuid.UUID
    kind: ImportKind
    status: JobStatus
    mapping: dict[str, Any]
    generation: int
    source_key: str | None
    source_url: str | None
    total_count: int
    checkpoint_index: int


def snapshot(row: ImportJob) -> JobSnap:
    return JobSnap(
        row.id,
        row.collection_id,
        row.kind,
        row.status,
        dict(row.mapping or {}),
        row.generation,
        row.source_key,
        row.source_url,
        row.total_count,
        row.checkpoint_index,
    )


def where(tenant: str, job_id: uuid.UUID) -> list[Any]:
    return [ImportJob.id == job_id, ImportJob.tenant_id == tenant]


async def load(db: Any, tenant: str, job_id: uuid.UUID, *, lock: bool = False) -> ImportJob | None:
    stmt = select(ImportJob).where(*where(tenant, job_id))
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_job(
    runtime: Runtime,
    tenant: str,
    collection_id: uuid.UUID,
    *,
    kind: ImportKind,
    mapping: Mapping,
    job_id: uuid.UUID | None = None,
    staged: tuple[str, int] | None = None,
    source_url: str | None = None,
    auto_run_prompts: bool = False,
    created_by: str | None = None,
) -> ImportJob:
    """A ``pending`` job whose source is ``staged`` (its key and feature count,
    the key's intent cleared in this transaction), or a ``staging`` one the
    runner fetches ``source_url`` for."""
    if (staged is None) == (source_url is None):
        raise TypeError("pass exactly one of staged= or source_url=")
    row = ImportJob(
        id=job_id or uuid.uuid4(),
        collection_id=collection_id,
        kind=kind,
        status=JobStatus.PENDING if staged else JobStatus.STAGING,
        mapping=mapping.model_dump(exclude_none=True),
        source_key=staged[0] if staged else None,
        staged_keys=[staged[0]] if staged else [],
        source_url=source_url,
        total_count=staged[1] if staged else 0,
        heartbeat_at=now(),
        auto_run_prompts=auto_run_prompts,
        created_by=created_by,
    )
    async with runtime.session_factory() as db:
        db.add(row)
        if staged:
            await clear_intents(db, [staged[0]])
        await finalize_session(db)
        await db.refresh(row)
        return row


async def returning_one(runtime: Runtime, stmt: Any) -> Any:
    async with runtime.session_factory() as db:
        found = (await db.execute(stmt.execution_options(**_SYNC))).first()
        await finalize_session(db)
    return found


async def start(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int
) -> JobSnap | None:
    """Take the job for a runner holding ``generation``; ``None`` if it moved on,
    is paused, finished or gone. ``staging`` until its source is stored."""
    async with runtime.session_factory() as db:
        row = await load(db, tenant, job_id, lock=True)
        if row is None or row.generation != generation or row.status not in ACTIVE:
            await db.rollback()
            return None
        row.status = JobStatus.RUNNING if row.source_key else JobStatus.STAGING
        row.heartbeat_at = row.updated_at = now()
        snap = snapshot(row)
        await finalize_session(db)
    return snap


async def heartbeat(runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int) -> bool:
    """Prove the runner is alive; ``False`` when it no longer owns the job."""
    stmt = (
        update(ImportJob)
        .where(
            *where(tenant, job_id),
            ImportJob.generation == generation,
            ImportJob.status.in_(ACTIVE),
        )
        .values(heartbeat_at=now())
        .returning(ImportJob.id)
    )
    return await returning_one(runtime, stmt) is not None


async def touch(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> None:
    stmt = update(ImportJob).where(*where(tenant, job_id)).values(heartbeat_at=now())
    await returning_one(runtime, stmt.returning(ImportJob.id))


async def claim_stale(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, stale_before: datetime | None = None
) -> int | None:
    """Take over an active job whose runner is gone: bump its generation (the old
    runner, if alive, stops at its next write) and return the new one. With
    ``stale_before`` only a heartbeat older than it qualifies - one claim wins."""
    conds = [*where(tenant, job_id), ImportJob.status.in_(ACTIVE)]
    if stale_before is not None:
        conds.append(ImportJob.heartbeat_at.is_(None) | (ImportJob.heartbeat_at < stale_before))
    stmt = (
        update(ImportJob)
        .where(*conds)
        .values(generation=ImportJob.generation + 1, heartbeat_at=now(), updated_at=now())
        .returning(ImportJob.generation)
    )
    found = await returning_one(runtime, stmt)
    return None if found is None else int(found[0])


async def live_collection(runtime: Runtime, tenant: str, collection_id: uuid.UUID):
    async with runtime.session_factory() as db:
        stmt = select(Collection).where(
            Collection.id == collection_id, Collection.tenant_id == tenant
        )
        found = (await db.execute(stmt)).scalar_one_or_none()
        if found is not None:
            db.expunge(found)  # a loaded, detached snapshot: the commit must not expire it
        await finalize_session(db)
    return found


async def resume_index(runtime: Runtime, tenant: str, job: JobSnap) -> int:
    """Where streaming restarts: the checkpoint, or - base64, whose image bytes
    live only in the source - the first recorded item still waiting for one."""
    if job.kind is not ImportKind.GEOJSON_BASE64:
        return job.checkpoint_index
    stmt = select(func.min(ImportItem.feature_index)).where(
        ImportItem.job_id == job.id,
        ImportItem.tenant_id == tenant,
        ImportItem.status == ItemStatus.PENDING,
        ImportItem.image_id.is_(None),
    )
    async with runtime.session_factory() as db:
        first = (await db.execute(stmt)).scalar()
        await finalize_session(db)
    return job.checkpoint_index if first is None else min(first, job.checkpoint_index)


async def pending_count(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> int:
    stmt = select(func.count()).where(
        ImportItem.job_id == job_id,
        ImportItem.tenant_id == tenant,
        ImportItem.status == ItemStatus.PENDING,
    )
    async with runtime.session_factory() as db:
        n = (await db.execute(stmt)).scalar_one()
        await finalize_session(db)
    return int(n)


async def bump(db: Any, tenant: str, job_id: uuid.UUID, deltas: dict[ItemStatus, int]) -> None:
    """Add to the job's counters (in the caller's transaction) and heartbeat it."""
    values: dict[str, Any] = {"heartbeat_at": now(), "updated_at": now()}
    for status, n in deltas.items():
        if n and status in COUNTERS:
            column = getattr(ImportJob, COUNTERS[status])
            # A decrement (retry-failed) is clamped at zero.
            values[COUNTERS[status]] = (
                column + n if n > 0 else case((column + n < 0, 0), else_=column + n)
            )
    stmt = update(ImportJob).where(*where(tenant, job_id)).values(**values)
    await db.execute(stmt.execution_options(**_SYNC))
