"""The ``resetting`` phase of restart and retry-failed: :func:`run_reset`.

A control first commits the job to ``resetting`` with a **new generation** and
its ``reset_mode`` (``controls``), so the intent is durable before any row
changes. Then this body resets items :data:`RESET_CHUNK` at a time, each batch
one short transaction that starts by **fencing** on that generation (and on
the job still ``resetting``): a newer restart, or reconcile reclaiming a
stalled reset, bumps the generation and this one stops - it can never delete
work a newer generation recorded. Batches are idempotent, so a reset killed
half way is simply run again by reconcile (``recover``), under the generation
it claimed.

* ``restart`` - delete every item that did not produce an image; the source is
  re-streamed from the start.
* ``restart_rows`` - a finished URL job whose source is gone: its rows carry
  every URL, so its failed items go back to ``pending`` instead.
* ``retry`` - failed items back to ``pending``, except failures the feature
  itself decides (``features.PARSE_CODES``), which a retry would only repeat.

Last, the counters are recounted from the rows, the job goes to ``pending``,
and a runner of the same generation is launched; it resumes where the rows say
(and hands out pending URL items itself).
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from simple_module_db import finalize_session, tenant_context
from sqlalchemy import delete, func, or_, select, update

from sm_images.imports import launch as handoff
from sm_images.imports.chunk import Stopped
from sm_images.imports.features import PARSE_CODES
from sm_images.imports.jobs import COUNTERS, SYNC, now, where
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import ImportKind, ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime, bind_runtime

__all__ = [
    "MODE_RESTART",
    "MODE_RETRY",
    "MODE_ROWS",
    "RESET_CHUNK",
    "reset_batch",
    "run_reset",
]

RESET_CHUNK: Final = 1000
MODE_RESTART: Final = "restart"
MODE_ROWS: Final = "restart_rows"
MODE_RETRY: Final = "retry"


async def _fence(db: Any, tenant: str, job_id: uuid.UUID, generation: int) -> Any:
    """``(reset_mode, kind)`` while this generation still owns the reset."""
    stmt = (
        update(ImportJob)
        .where(
            *where(tenant, job_id),
            ImportJob.generation == generation,
            ImportJob.status == JobStatus.RESETTING,
        )
        .values(heartbeat_at=now(), updated_at=now())
        .returning(ImportJob.reset_mode, ImportJob.kind)
        .execution_options(**SYNC)
    )
    return (await db.execute(stmt)).first()


def _page(tenant: str, job_id: uuid.UUID, mode: str, kind: ImportKind) -> Any:
    stmt = select(ImportItem.id).where(ImportItem.job_id == job_id, ImportItem.tenant_id == tenant)
    if mode == MODE_RESTART:
        return stmt.where(ImportItem.status != ItemStatus.DONE).limit(RESET_CHUNK)
    stmt = stmt.where(
        ImportItem.status == ItemStatus.FAILED,
        or_(ImportItem.last_error.is_(None), ImportItem.last_error.not_in(PARSE_CODES)),
    )
    if kind is ImportKind.GEOJSON_URL:
        stmt = stmt.where(ImportItem.url.is_not(None))
    return stmt.limit(RESET_CHUNK)


async def reset_batch(runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int) -> int:
    """Reset one batch under the fence; how many rows it changed. Raises
    :class:`Stopped` when the generation moved on."""
    async with runtime.session_factory() as db:
        fenced = await _fence(db, tenant, job_id, generation)
        if fenced is None:
            await db.rollback()
            raise Stopped()
        mode, kind = fenced
        ids = list((await db.execute(_page(tenant, job_id, mode, kind))).scalars())
        if ids:
            target = [ImportItem.id.in_(ids), ImportItem.tenant_id == tenant]
            if mode == MODE_RESTART:
                stmt: Any = delete(ImportItem).where(*target)
            else:
                stmt = (
                    update(ImportItem)
                    .where(*target, ImportItem.status == ItemStatus.FAILED)
                    .values(
                        status=ItemStatus.PENDING,
                        attempts=0,
                        last_error=None,
                        claim_token=None,
                        claim_expires_at=None,
                        claim_generation=None,
                        updated_at=now(),
                    )
                )
            await db.execute(stmt.execution_options(**SYNC))
            counted = ImportJob.reset_progress + len(ids)  # the poison-job breaker's progress
            bump = update(ImportJob).where(*where(tenant, job_id)).values(reset_progress=counted)
            await db.execute(bump.execution_options(**SYNC))
        await finalize_session(db)
    return len(ids)


async def _finish_reset(runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int) -> None:
    counts_stmt = (
        select(ImportItem.status, func.count())
        .where(ImportItem.job_id == job_id, ImportItem.tenant_id == tenant)
        .group_by(ImportItem.status)
    )
    async with runtime.session_factory() as db:
        if await _fence(db, tenant, job_id, generation) is None:
            await db.rollback()
            raise Stopped()
        counts = dict((await db.execute(counts_stmt)).tuples().all())
        values: dict[str, Any] = {name: counts.get(st, 0) for st, name in COUNTERS.items()}
        stmt = (
            update(ImportJob)
            .where(*where(tenant, job_id), ImportJob.generation == generation)
            .values(**values, status=JobStatus.PENDING, reset_mode=None, heartbeat_at=now())
        )
        await db.execute(stmt.execution_options(**SYNC))
        await finalize_session(db)


async def run_reset(runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int) -> str:
    """Run (or resume) a reset to the end and launch the runner; returns
    ``reset`` or ``stopped`` (a newer generation owns the job)."""
    with tenant_context(tenant), bind_runtime(runtime):
        try:
            while await reset_batch(runtime, tenant, job_id, generation) >= RESET_CHUNK:
                pass
            await _finish_reset(runtime, tenant, job_id, generation)
        except Stopped:
            return "stopped"
        await handoff.launch_runner(runtime, tenant, job_id, generation)
        return "reset"
