"""The regroup job's record: creation, the generation fence, claim, cancel, hand-off.

Every runner write is a conditional ``UPDATE`` naming the tenant and the
generation the runner holds (the import jobs' pattern, ``imports.jobs``): a
reconcile claim or a cancel bumps the generation, and the runner it replaced
stops at its next write. A chunk's counters and cursor are written in the
chunk's own transaction (:func:`advance`), so a replaced runner's chunk rolls
back instead of being counted twice.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import case, or_, select, update
from sqlalchemy.exc import IntegrityError

from sm_images import constants
from sm_images.errors import Conflict
from sm_images.models import RegroupJob
from sm_images.models.regroup_job import CANCELLED, COMPLETED, FAILED, RUNNING
from sm_images.pipeline.runtime import Runtime
from sm_images.services.regroup import Tally

__all__ = [
    "Snap",
    "advance",
    "cancel",
    "claim_stale",
    "create",
    "finish",
    "launch",
    "snapshot",
]

SYNC = {"synchronize_session": False}
COUNTERS = tuple(vars(Tally()))
STALLED = "stalled"


def now() -> datetime:
    return datetime.now(UTC)


def _where(tenant: str, job_id: uuid.UUID) -> list[Any]:
    return [RegroupJob.id == job_id, RegroupJob.tenant_id == tenant]


def _live(generation: int) -> list[Any]:
    return [
        RegroupJob.generation == generation,
        RegroupJob.status == RUNNING,
        RegroupJob.finished_at.is_(None),
    ]


@dataclass(frozen=True)
class Snap:
    """Plain values of a job, safe to hold across sessions."""

    id: uuid.UUID
    collection_id: uuid.UUID
    pattern: str
    reassign: bool
    dry_run: bool
    generation: int
    run_as: str | None
    access_basis: str | None
    cursor: tuple[datetime, uuid.UUID] | None
    began: datetime | None = None
    """When the job was created: groups older than this pre-existed it."""


async def create(
    runtime: Runtime,
    tenant: str,
    collection_id: uuid.UUID,
    *,
    pattern: str,
    reassign: bool,
    dry_run: bool,
    run_as: str | None,
    access_basis: str | None,
) -> uuid.UUID:
    """Record a job (committed before anything is handed on). One unfinished
    job per collection: a second is a 409, also under a race (the partial
    unique index)."""
    async with runtime.session_factory() as db:
        busy = select(RegroupJob.id).where(
            RegroupJob.collection_id == collection_id,
            RegroupJob.tenant_id == tenant,
            RegroupJob.finished_at.is_(None),
        )
        if (await db.execute(busy.limit(1))).first() is not None:
            raise _active()
        row = RegroupJob(
            collection_id=collection_id,
            pattern=pattern,
            reassign=reassign,
            dry_run=dry_run,
            run_as=run_as,
            access_basis=access_basis,
            heartbeat_at=now(),
        )
        db.add(row)
        job_id = row.id
        try:
            await finalize_session(db)
        except IntegrityError:
            raise _active() from None
        return job_id


def _active() -> Conflict:
    err = Conflict("A regroup is already running for this collection")
    err.code = constants.CODE_REGROUP_ACTIVE
    return err


async def snapshot(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> Snap | None:
    async with runtime.session_factory() as db:
        row = (
            await db.execute(select(RegroupJob).where(*_where(tenant, job_id)))
        ).scalar_one_or_none()
        snap = None
        if row is not None:
            cursor = None if row.cursor_id is None else (row.cursor_at, row.cursor_id)
            snap = Snap(
                row.id,
                row.collection_id,
                row.pattern,
                row.reassign,
                row.dry_run,
                row.generation,
                row.run_as,
                row.access_basis,
                cursor,
                row.created_at,
            )
        await finalize_session(db)
    return snap


async def advance(
    db: Any,
    tenant: str,
    job: Snap,
    generation: int,
    cursor: tuple[datetime, uuid.UUID],
    tally: Tally,
) -> bool:
    """Move the cursor past the chunk just applied and add its counters - only
    if this runner still owns the job and the cursor is where it read it."""
    at = (
        RegroupJob.cursor_id.is_(None)
        if job.cursor is None
        else RegroupJob.cursor_id == job.cursor[1]
    )
    values = {name: getattr(RegroupJob, name) + getattr(tally, name) for name in COUNTERS}
    stmt = (
        update(RegroupJob)
        .where(*_where(tenant, job.id), *_live(generation), at)
        .values(
            cursor_at=cursor[0], cursor_id=cursor[1], heartbeat_at=now(), updated_at=now(), **values
        )
        .returning(RegroupJob.id)
        .execution_options(**SYNC)
    )
    return (await db.execute(stmt)).first() is not None


async def finish(
    runtime: Runtime,
    tenant: str,
    job_id: uuid.UUID,
    generation: int,
    *,
    status: str = COMPLETED,
    error_code: str | None = None,
) -> bool:
    stmt = (
        update(RegroupJob)
        .where(*_where(tenant, job_id), *_live(generation))
        .values(
            status=status,
            error_code=error_code,
            finished_at=now(),
            heartbeat_at=now(),
            updated_at=now(),
        )
        .returning(RegroupJob.id)
        .execution_options(**SYNC)
    )
    async with runtime.session_factory() as db:
        done = (await db.execute(stmt)).first() is not None
        await finalize_session(db)
    return done


async def cancel(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, *, error_code: str | None = None
) -> bool:
    """Stop an unfinished job: the generation moves on, so a runner mid-chunk
    loses at its next write. ``False`` when it had already finished."""
    stmt = (
        update(RegroupJob)
        .where(*_where(tenant, job_id), RegroupJob.finished_at.is_(None))
        .values(
            status=CANCELLED,
            error_code=error_code,
            generation=RegroupJob.generation + 1,
            finished_at=now(),
            updated_at=now(),
        )
        .returning(RegroupJob.id)
        .execution_options(**SYNC)
    )
    async with runtime.session_factory() as db:
        done = (await db.execute(stmt)).first() is not None
        await finalize_session(db)
    return done


async def claim_stale(
    runtime: Runtime, tenant: str, stale_before: datetime
) -> list[tuple[uuid.UUID, int]]:
    """Take over every running job whose heartbeat is older than ``stale_before``:
    a new generation each (the old runner, if alive, stops). A claim with no
    progress since the last one is a strike; past the limit the job fails as
    ``stalled`` instead of being relaunched. Returns ``(job_id, generation)``."""
    stmt = (
        update(RegroupJob)
        .where(
            RegroupJob.tenant_id == tenant,
            RegroupJob.status == RUNNING,
            RegroupJob.finished_at.is_(None),
            or_(RegroupJob.heartbeat_at.is_(None), RegroupJob.heartbeat_at < stale_before),
        )
        .values(
            generation=RegroupJob.generation + 1,
            heartbeat_at=now(),
            updated_at=now(),
            relaunches=case(
                (RegroupJob.scanned == RegroupJob.progress_mark, RegroupJob.relaunches + 1),
                else_=1,
            ),
            progress_mark=RegroupJob.scanned,
        )
        .returning(RegroupJob.id, RegroupJob.generation, RegroupJob.relaunches)
        .execution_options(**SYNC)
    )
    async with runtime.session_factory() as db:
        rows = list((await db.execute(stmt)).all())
        await finalize_session(db)
    live: list[tuple[uuid.UUID, int]] = []
    for job_id, generation, relaunches in rows:
        if relaunches > constants.REGROUP_RELAUNCH_LIMIT:
            await finish(runtime, tenant, job_id, generation, status=FAILED, error_code=STALLED)
        else:
            live.append((job_id, generation))
    return live


async def launch(runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int) -> None:
    """Hand the job to a runner: inline when eager, a message on
    ``images_imports`` otherwise (stamped with the tenant header)."""
    if runtime.is_eager():
        # Imported here: the runner imports this module, and a broker-only process
        # never needs it.
        from sm_images.regroup.runner import run_regroup

        await run_regroup(runtime, tenant, job_id, generation)
        return
    # Celery stays out of the module's import time (see ``sm_images.tasks``).
    from background_tasks.tenant_context import TENANT_HEADER

    from sm_images.task_config import QUEUE_IMPORTS
    from sm_images.tasks import run_regroup_task

    run_regroup_task.s(str(job_id), generation).apply_async(
        queue=QUEUE_IMPORTS, headers={TENANT_HEADER: tenant}
    )
