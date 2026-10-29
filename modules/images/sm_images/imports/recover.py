"""Import recovery for ``images.reconcile`` (plan decision 6), one tenant at a time.

Delivery is at-most-once, so two things can be lost:

* **a runner or a reset** - a job ``pending``, ``staging``, ``running`` or
  ``resetting`` whose heartbeat is older than the cutoff (a lost message, a
  killed worker). It is reclaimed
  with :func:`claims.claim_stale` - one conditional ``UPDATE`` that bumps the
  generation, so of two reconcilers only one wins and a still-living runner
  stops at its next write - and a new runner (or, for ``resetting``, the reset
  again: its batches are idempotent) is launched. A runner resumes from the
  checkpoint (or, base64, the first item without an image); a fully recorded
  job does not re-stream, it hands out its pending items and completes;
* **a download** - a URL item still ``pending``, held by no live claim and
  untouched since the cutoff, in a ``running`` job. It is handed out again for
  the job's current generation; the claim makes a surfacing original skip it.
  An item deferred until a time (a Retry-After) waits for it (``next_attempt_at``).

**Bounded passes.** One tenant's pass reclaims at most :data:`JOBS_PER_PASS`
jobs and re-sends at most :data:`ITEMS_PER_PASS` items, the longest-waiting
first; what it sends is freshened, so the next pass continues with the rest.

**The poison-job breaker.** Each claim of a generation a worker actually
started counts the relaunch, in the same ``UPDATE`` (``claims.claim_stale``) -
a message stuck in a backed-up queue is no strike: ``relaunches`` grows while ``claims.progress``
(the checkpoint, every settlement - done, duplicate or failed - and the items a
reset changed) stays where it was at the last one, and resets to 1 when it
moved. A job found stale again after :data:`RELAUNCH_LIMIT` relaunches without
progress is failed ``stalled`` under the generation just claimed (an ERROR is
logged) instead of relaunched, so no unanticipated failure loops forever. A
control an operator uses (resume, restart, retry-failed) resets the count.

A ZIP job still ``uploading`` is none of this: it has no runner until its
archive is sealed. Once its upload session is gone it is failed instead
(:func:`expire_uploads`).

The caller (reconcile) has bound the tenant; every statement names it too.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Final

from simple_module_db import finalize_session
from sqlalchemy import and_, or_, select, update

from sm_images.imports import claims, jobs, terminal
from sm_images.imports import launch as handoff
from sm_images.models import ImportItem, ImportJob, UploadSession, UploadStatus
from sm_images.models.enums import ImportKind, ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime

__all__ = [
    "ITEMS_PER_PASS",
    "ITEM_BATCH",
    "JOBS_PER_PASS",
    "RELAUNCH_LIMIT",
    "STALLED",
    "expire_uploads",
    "recover_imports",
]

logger = logging.getLogger(__name__)

ITEM_BATCH: Final = 1000
JOBS_PER_PASS: Final = 100
"""Stale jobs one tenant's pass reclaims; the rest wait for the next pass
(each reclaim freshens its heartbeat, so the next pass reaches the others)."""
ITEMS_PER_PASS: Final = 1000
"""Downloads one tenant's pass re-sends, so one tenant's backlog cannot hold
up the others' recovery."""
RELAUNCH_LIMIT: Final = 5
"""Relaunches without progress before a job is failed as :data:`STALLED`."""
STALLED: Final = "stalled"


async def _stale_jobs(
    runtime: Runtime, tenant: str, cutoff: datetime
) -> list[tuple[uuid.UUID, JobStatus]]:
    stmt = (
        select(ImportJob.id, ImportJob.status)
        .where(
            ImportJob.tenant_id == tenant,
            ImportJob.status.in_(jobs.CLAIMABLE),
            or_(ImportJob.heartbeat_at.is_(None), ImportJob.heartbeat_at < cutoff),
        )
        .order_by(ImportJob.heartbeat_at)
        .limit(JOBS_PER_PASS)
    )
    async with runtime.session_factory() as db:
        rows = [(i, st) for i, st in (await db.execute(stmt)).all()]
        await finalize_session(db)
    return rows


async def _stale_items(
    runtime: Runtime, tenant: str, cutoff: datetime, now: datetime
) -> dict[tuple[uuid.UUID, int], list[int]]:
    """At most :data:`ITEMS_PER_PASS` items to re-send, oldest first."""
    stmt = (
        select(ImportItem.id, ImportItem.job_id, ImportJob.generation)
        .join(ImportJob, ImportJob.id == ImportItem.job_id)
        .where(
            ImportItem.tenant_id == tenant,
            ImportJob.tenant_id == tenant,
            ImportJob.status == JobStatus.RUNNING,
            ImportJob.kind == ImportKind.GEOJSON_URL,
            ImportItem.status == ItemStatus.PENDING,
            or_(ImportItem.updated_at.is_(None), ImportItem.updated_at < cutoff),
            or_(ImportItem.claim_token.is_(None), ImportItem.claim_expires_at < now),
            or_(ImportItem.next_attempt_at.is_(None), ImportItem.next_attempt_at <= now),
        )
        .order_by(ImportItem.updated_at, ImportItem.id)
        .limit(ITEMS_PER_PASS)
    )
    async with runtime.session_factory() as db:
        rows = list((await db.execute(stmt)).all())
        await finalize_session(db)
    out: dict[tuple[uuid.UUID, int], list[int]] = defaultdict(list)
    for item_id, job_id, generation in rows:
        out[(job_id, int(generation))].append(int(item_id))
    return out


async def _mark_sent(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int, ids: list[int]
) -> None:
    """Freshen re-sent items, so the next pass moves on to the rest (the
    continuation) instead of sending these again before a worker got to them.
    Only items still pending and unclaimed, of the job at this generation."""
    current = select(ImportJob.id).where(
        *jobs.where(tenant, job_id), ImportJob.generation == generation
    )
    stmt = (
        update(ImportItem)
        .where(
            ImportItem.id.in_(ids),
            ImportItem.tenant_id == tenant,
            ImportItem.status == ItemStatus.PENDING,
            ImportItem.claim_token.is_(None),
            ImportItem.job_id.in_(current.scalar_subquery()),
        )
        .values(updated_at=jobs.now())
        .execution_options(**jobs.SYNC)
    )
    async with runtime.session_factory() as db:
        await db.execute(stmt)
        await finalize_session(db)


async def _relaunches(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> int:
    stmt = select(ImportJob.relaunches).where(*jobs.where(tenant, job_id))
    async with runtime.session_factory() as db:
        n = (await db.execute(stmt)).scalar_one_or_none()
        await finalize_session(db)
    return int(n or 0)


async def expire_uploads(runtime: Runtime, tenant: str) -> int:
    """Fail ``uploading`` ZIP jobs whose upload session expired, was aborted or
    is gone (``upload_expired``); the reaper deletes the parts. How many."""
    from sm_images.imports.zip_upload import fail_upload

    gone = or_(
        UploadSession.id.is_(None),
        UploadSession.status == UploadStatus.ABORTED,
        and_(UploadSession.status == UploadStatus.OPEN, UploadSession.expires_at <= jobs.now()),
    )
    stmt = (
        select(ImportJob)
        .outerjoin(UploadSession, UploadSession.id == ImportJob.upload_session_id)
        .where(ImportJob.tenant_id == tenant, ImportJob.status == JobStatus.UPLOADING, gone)
        .limit(ITEM_BATCH)
    )
    async with runtime.session_factory() as db:
        rows = list((await db.execute(stmt)).scalars())
        db.expunge_all()
        await finalize_session(db)
    for row in rows:
        await fail_upload(runtime, tenant, row, "upload_expired")
    return len(rows)


async def recover_imports(runtime: Runtime, tenant: str, cutoff: datetime) -> tuple[int, int]:
    """Relaunch stale runners and re-send stale downloads; ``(jobs, items)``.
    ZIP jobs whose upload never arrived are failed first (:func:`expire_uploads`)."""
    try:
        await expire_uploads(runtime, tenant)
    except Exception:
        logger.exception("images.reconcile.expire_uploads_failed tenant=%s", tenant)
    relaunched = 0
    for job_id, status in await _stale_jobs(runtime, tenant, cutoff):
        generation = await claims.claim_stale(runtime, tenant, job_id, cutoff)
        if generation is None:
            continue  # someone else claimed it, or it moved on
        if await _relaunches(runtime, tenant, job_id) > RELAUNCH_LIMIT:
            logger.error("images.reconcile.import_stalled job=%s", job_id)
            await terminal.finish(
                runtime,
                tenant,
                job_id,
                generation,
                JobStatus.FAILED,
                STALLED,
                from_=jobs.CLAIMABLE,
            )
            continue
        relaunched += 1
        launcher = handoff.launch_reset if status is JobStatus.RESETTING else handoff.launch_runner
        try:
            await launcher(runtime, tenant, job_id, generation)
        except Exception:
            logger.exception("images.reconcile.import_runner_failed job=%s", job_id)
    sent = 0
    stale = await _stale_items(runtime, tenant, cutoff, datetime.now(UTC))
    for (job_id, generation), ids in stale.items():
        sent += len(ids)
        try:
            await _mark_sent(runtime, tenant, job_id, generation, ids)
            await handoff.launch_downloads(runtime, tenant, job_id, generation, ids)
        except Exception:
            logger.exception("images.reconcile.import_downloads_failed job=%s", job_id)
    return relaunched, sent
