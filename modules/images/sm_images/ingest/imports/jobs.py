"""The import job's record: creation, the generation fence, counters.

Every write that a runner or a download makes to a job is a conditional
``UPDATE``, never a read-modify-write of a loaded row:

* **the generation fence** - a runner holds ``generation``; a restart, a
  resume and reconcile's reclaim bump it, so a runner from before stops at its
  next write (:func:`start`, :func:`heartbeat`, ``chunk.advance_checkpoint``);
* **counters** are increments (``done_count + n``, :func:`bump`), so
  concurrent downloads never lose one another's - and a settlement's
  increment is itself fenced (``running`` and the settler's generation), in
  the same transaction as its image, so work from before a pause, restart or
  reclaim rolls back instead of landing.

Completion and the other terminal moves are in :mod:`.terminal`.

Every statement names the tenant explicitly (Core ``UPDATE`` is invisible to
the ORM tenancy guard).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Final

from simple_module_db import finalize_session
from sqlalchemy import case, func, select, update

from sm_images.core.clock import utcnow as now
from sm_images.core.constants import NO_SYNC
from sm_images.core.storage.intents import clear_intents
from sm_images.ingest.imports.mapping import Mapping
from sm_images.models import Collection, ImportItem, ImportJob
from sm_images.models.enums import ImportKind, ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime, first_row

__all__ = [
    "ACTIVE",
    "CLAIMABLE",
    "COUNTERS",
    "SYNC",
    "TERMINAL",
    "JobSnap",
    "bump",
    "create_job",
    "heartbeat",
    "load",
    "now",
    "pending_count",
    "returning_one",
    "snapshot",
    "start",
    "where",
]

ACTIVE: Final = (JobStatus.PENDING, JobStatus.STAGING, JobStatus.RUNNING)
CLAIMABLE: Final = (*ACTIVE, JobStatus.RESETTING)
"""What reconcile may take over once its heartbeat is stale."""
TERMINAL: Final = (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
COUNTERS: Final = {
    ItemStatus.DONE: "done_count",
    ItemStatus.DUPLICATE: "duplicate_count",
    ItemStatus.FAILED: "failed_count",
}
SYNC: Final = NO_SYNC  # re-exported: the import modules spell it ``jobs.SYNC``


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
    auto_run_prompts: bool = True
    """Whether the job's images get the collection's ``auto_run`` prompts."""


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
        row.auto_run_prompts,
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
    auto_run_prompts: bool = True,
    created_by: str | None = None,
    access_basis: str | None = None,
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
        run_as=created_by,
        access_basis=access_basis,
    )
    async with runtime.session_factory() as db:
        db.add(row)
        if staged:
            await clear_intents(db, [staged[0]])
        await finalize_session(db)
        await db.refresh(row)
        return row


async def returning_one(runtime: Runtime, stmt: Any) -> Any:
    return await first_row(runtime, stmt.execution_options(**SYNC))


def needs_staging(row: Any) -> bool:
    """No stored source and features still to record. A finished URL job whose
    source was cleaned up has every feature recorded and needs none."""
    recorded = row.total_count > 0 and row.checkpoint_index >= row.total_count
    return row.source_key is None and not recorded


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
        row.status = JobStatus.STAGING if needs_staging(row) else JobStatus.RUNNING
        row.heartbeat_at = row.updated_at = row.started_at = now()
        row.started_generation = generation  # this relaunch ran (``claims``)
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


async def bump(
    db: Any,
    tenant: str,
    job_id: uuid.UUID,
    deltas: dict[ItemStatus, int],
    generation: int,
) -> bool:
    """Add to the job's counters (in the caller's transaction) and heartbeat it -
    only while the job is ``running`` in ``generation`` and its collection is
    not in the trash. ``False`` otherwise,
    and the caller rolls its whole transaction back (the fence every item
    settlement commits behind)."""
    values: dict[str, Any] = {"heartbeat_at": now(), "updated_at": now()}
    for status, n in deltas.items():
        if n and status in COUNTERS:
            column = getattr(ImportJob, COUNTERS[status])
            # A decrement (retry-failed) is clamped at zero.
            values[COUNTERS[status]] = (
                column + n if n > 0 else case((column + n < 0, 0), else_=column + n)
            )
    live = select(Collection.id).where(
        Collection.tenant_id == tenant, Collection.is_deleted.is_(False)
    )
    conds = [
        *where(tenant, job_id),
        ImportJob.generation == generation,
        ImportJob.status == JobStatus.RUNNING,
        ImportJob.collection_id.in_(live.scalar_subquery()),  # not trashed meanwhile
    ]
    stmt = update(ImportJob).where(*conds).values(**values).returning(ImportJob.id)
    return (await db.execute(stmt.execution_options(**SYNC))).first() is not None
