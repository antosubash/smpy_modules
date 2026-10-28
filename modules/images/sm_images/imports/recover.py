"""Import recovery for ``images.reconcile`` (plan decision 6), one tenant at a time.

Delivery is at-most-once, so two things can be lost:

* **a runner** - a job ``pending``, ``staging`` or ``running`` whose heartbeat
  is older than the cutoff (a lost message, a killed worker). It is reclaimed
  with :func:`jobs.claim_stale` - one conditional ``UPDATE`` that bumps the
  generation, so of two reconcilers only one wins and a still-living runner
  stops at its next write - and a new runner is launched. It resumes from the
  checkpoint (or, base64, the first item without an image); a fully recorded
  job does not re-stream, it only tries to complete;
* **a download** - a URL item still ``pending`` and untouched since the
  cutoff in a ``running`` job. It is handed out again; the message carries
  when it was sent, so the lost original, should it surface, does not fetch it
  a second time.

The caller (reconcile) has bound the tenant; every statement names it too.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Final

from simple_module_db import finalize_session
from sqlalchemy import or_, select

from sm_images.imports import jobs
from sm_images.imports import launch as handoff
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import ImportKind, ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime

__all__ = ["ITEM_BATCH", "recover_imports"]

logger = logging.getLogger(__name__)

ITEM_BATCH: Final = 1000


async def _stale_jobs(runtime: Runtime, tenant: str, cutoff: datetime) -> list[uuid.UUID]:
    stmt = select(ImportJob.id).where(
        ImportJob.tenant_id == tenant,
        ImportJob.status.in_(jobs.ACTIVE),
        or_(ImportJob.heartbeat_at.is_(None), ImportJob.heartbeat_at < cutoff),
    )
    async with runtime.session_factory() as db:
        ids = list((await db.execute(stmt)).scalars())
        await finalize_session(db)
    return ids


async def _stale_items(
    runtime: Runtime, tenant: str, cutoff: datetime
) -> dict[uuid.UUID, list[int]]:
    out: dict[uuid.UUID, list[int]] = defaultdict(list)
    after = 0
    while True:
        stmt = (
            select(ImportItem.id, ImportItem.job_id)
            .join(ImportJob, ImportJob.id == ImportItem.job_id)
            .where(
                ImportItem.tenant_id == tenant,
                ImportJob.tenant_id == tenant,
                ImportJob.status == JobStatus.RUNNING,
                ImportJob.kind == ImportKind.GEOJSON_URL,
                ImportItem.status == ItemStatus.PENDING,
                or_(ImportItem.updated_at.is_(None), ImportItem.updated_at < cutoff),
                ImportItem.id > after,
            )
            .order_by(ImportItem.id)
            .limit(ITEM_BATCH)
        )
        async with runtime.session_factory() as db:
            rows = list((await db.execute(stmt)).all())
            await finalize_session(db)
        for item_id, job_id in rows:
            out[job_id].append(int(item_id))
        if len(rows) < ITEM_BATCH:
            return out
        after = int(rows[-1][0])


async def recover_imports(runtime: Runtime, tenant: str, cutoff: datetime) -> tuple[int, int]:
    """Relaunch stale runners and re-send stale downloads; ``(jobs, items)``."""
    relaunched = 0
    for job_id in await _stale_jobs(runtime, tenant, cutoff):
        generation = await jobs.claim_stale(runtime, tenant, job_id, cutoff)
        if generation is None:
            continue  # someone else claimed it, or it moved on
        relaunched += 1
        try:
            await handoff.launch_runner(runtime, tenant, job_id, generation)
        except Exception:
            logger.exception("images.reconcile.import_runner_failed job=%s", job_id)
    sent = 0
    for job_id, ids in (await _stale_items(runtime, tenant, cutoff)).items():
        sent += len(ids)
        try:
            await handoff.launch_downloads(runtime, tenant, job_id, ids)
        except Exception:
            logger.exception("images.reconcile.import_downloads_failed job=%s", job_id)
    return relaunched, sent
