"""Import recovery for ``images.reconcile`` (plan decision 6), one tenant at a time.

Delivery is at-most-once, so two things can be lost:

* **a runner or a reset** - a job ``pending``, ``staging``, ``running`` or
  ``resetting`` whose heartbeat is older than the cutoff (a lost message, a
  killed worker). It is reclaimed
  with :func:`jobs.claim_stale` - one conditional ``UPDATE`` that bumps the
  generation, so of two reconcilers only one wins and a still-living runner
  stops at its next write - and a new runner (or, for ``resetting``, the reset
  again: its batches are idempotent) is launched. A runner resumes from the
  checkpoint (or, base64, the first item without an image); a fully recorded
  job does not re-stream, it hands out its pending items and completes;
* **a download** - a URL item still ``pending``, held by no live claim and
  untouched since the cutoff, in a ``running`` job. It is handed out again for
  the job's current generation; the claim makes a surfacing original skip it.

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
from sqlalchemy import and_, or_, select

from sm_images.imports import jobs
from sm_images.imports import launch as handoff
from sm_images.models import ImportItem, ImportJob, UploadSession, UploadStatus
from sm_images.models.enums import ImportKind, ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime

__all__ = ["ITEM_BATCH", "recover_imports"]

logger = logging.getLogger(__name__)

ITEM_BATCH: Final = 1000


async def _stale_jobs(
    runtime: Runtime, tenant: str, cutoff: datetime
) -> list[tuple[uuid.UUID, JobStatus]]:
    stmt = select(ImportJob.id, ImportJob.status).where(
        ImportJob.tenant_id == tenant,
        ImportJob.status.in_(jobs.CLAIMABLE),
        or_(ImportJob.heartbeat_at.is_(None), ImportJob.heartbeat_at < cutoff),
    )
    async with runtime.session_factory() as db:
        rows = [(i, st) for i, st in (await db.execute(stmt)).all()]
        await finalize_session(db)
    return rows


async def _stale_items(
    runtime: Runtime, tenant: str, cutoff: datetime, now: datetime
) -> dict[tuple[uuid.UUID, int], list[int]]:
    out: dict[tuple[uuid.UUID, int], list[int]] = defaultdict(list)
    after = 0
    while True:
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
                ImportItem.id > after,
            )
            .order_by(ImportItem.id)
            .limit(ITEM_BATCH)
        )
        async with runtime.session_factory() as db:
            rows = list((await db.execute(stmt)).all())
            await finalize_session(db)
        for item_id, job_id, generation in rows:
            out[(job_id, int(generation))].append(int(item_id))
        if len(rows) < ITEM_BATCH:
            return out
        after = int(rows[-1][0])


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
        generation = await jobs.claim_stale(runtime, tenant, job_id, cutoff)
        if generation is None:
            continue  # someone else claimed it, or it moved on
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
            await handoff.launch_downloads(runtime, tenant, job_id, generation, ids)
        except Exception:
            logger.exception("images.reconcile.import_downloads_failed job=%s", job_id)
    return relaunched, sent
