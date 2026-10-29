"""Reconcile's takeover of a silent job: :func:`claim_stale`, and the progress
the poison-job breaker watches (:func:`progress`).

**Only a relaunch that ran is a strike.** A worker that takes a job stamps
``started_generation`` (``jobs.start``; a reset on its every fenced batch). A
claim counts a relaunch toward ``recover.RELAUNCH_LIMIT`` only when the
generation it replaces was started: a message still sitting in a backed-up
queue has failed at nothing, so reclaiming it again leaves the count alone.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import case, update

from sm_images.imports.jobs import CLAIMABLE, now, returning_one, where
from sm_images.models import ImportJob
from sm_images.pipeline.runtime import Runtime

__all__ = ["claim_stale", "progress"]


def progress() -> Any:
    """How far a job has got, as one number: what the poison-job breaker watches.
    Every settlement counts (done, duplicate or failed), and so does a reset batch."""
    j = ImportJob
    settled = j.done_count + j.duplicate_count + j.failed_count
    return j.checkpoint_index + settled + j.reset_progress


def _relaunches() -> Any:
    """The relaunch count after this claim: unchanged when the replaced
    generation never started, ``+ 1`` when it started and nothing progressed
    since the last claim, else back to 1."""
    j = ImportJob
    started = j.started_generation.is_not(None) & (j.started_generation == j.generation)
    return case(
        (~started, j.relaunches),
        (progress() == j.progress_mark, j.relaunches + 1),
        else_=1,
    )


async def claim_stale(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, stale_before: datetime | None = None
) -> int | None:
    """Take over an active or resetting job whose worker is gone: bump its
    generation (the old one, if alive, stops at its next write) and return the
    new one. With ``stale_before`` only a heartbeat older than it qualifies -
    one claim wins. The same ``UPDATE`` counts the relaunch (:func:`_relaunches`)."""
    conds = [*where(tenant, job_id), ImportJob.status.in_(CLAIMABLE)]
    if stale_before is not None:
        conds.append(ImportJob.heartbeat_at.is_(None) | (ImportJob.heartbeat_at < stale_before))
    stmt = (
        update(ImportJob)
        .where(*conds)
        .values(
            generation=ImportJob.generation + 1,
            heartbeat_at=now(),
            updated_at=now(),
            relaunches=_relaunches(),
            progress_mark=progress(),
        )
        .returning(ImportJob.generation)
    )
    found = await returning_one(runtime, stmt)
    return None if found is None else int(found[0])
