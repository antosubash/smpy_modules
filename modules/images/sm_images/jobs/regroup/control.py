"""Regroup job upkeep that is not a runner's own write: the per-job group set,
the collection-delete cancel and reconcile's claim of a silent job."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import case, or_, update

from sm_images.core import constants
from sm_images.core.clock.db import dialect_insert
from sm_images.jobs.regroup.jobs import STALLED, SYNC, finish, now
from sm_images.models import RegroupJob, RegroupJobGroup
from sm_images.models.regroup_job import CANCELLED, FAILED, RUNNING
from sm_images.pipeline.runtime import Runtime

__all__ = ["cancel_for_collection", "claim_stale", "note_groups"]


async def note_groups(
    db: Any, tenant: str, job_id: uuid.UUID, group_ids: Sequence[uuid.UUID]
) -> int:
    """Record that this job used these pre-existing groups; returns how many were
    new to the job. The set lives in ``images_regroup_job_group`` and is written
    in the chunk's own transaction, so a rolled-back chunk leaves no trace and a
    resumed job never counts a group twice."""
    if not group_ids:
        return 0
    insert = dialect_insert(db)
    stmt = (
        insert(RegroupJobGroup)
        .values([{"tenant_id": tenant, "job_id": job_id, "group_id": g} for g in group_ids])
        .on_conflict_do_nothing(index_elements=["job_id", "group_id"])
        .returning(RegroupJobGroup.group_id)
    )
    return len((await db.execute(stmt)).all())


async def cancel_for_collection(db: Any, tenant: str, collection_id: uuid.UUID) -> int:
    """Cancel every unfinished regroup of a collection being trashed, in the
    caller's transaction (the one that trashes it), bumping each generation so a
    runner in flight loses at its next write. How many."""
    stmt = (
        update(RegroupJob)
        .where(
            RegroupJob.tenant_id == tenant,
            RegroupJob.collection_id == collection_id,
            RegroupJob.finished_at.is_(None),
        )
        .values(
            status=CANCELLED,
            generation=RegroupJob.generation + 1,
            finished_at=now(),
            updated_at=now(),
        )
        .returning(RegroupJob.id)
        .execution_options(**SYNC)
    )
    return len((await db.execute(stmt)).all())


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
