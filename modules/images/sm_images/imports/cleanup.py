"""Removing an import: :func:`delete_job`, and the janitor's staging sweep.

**Delete** first fences the job (a new generation, ``cancelled``), so a runner
or download still in flight stops at its next write or finds nothing. Its
staged keys get write-ahead intents *before* the row goes - once the row is
gone nothing else names those objects, and an intent is what lets the
janitor's intent pass still reap one whose delete failed here. The images the
job created stay; they belong to the collection.

**The sweep** (:func:`reap_staging`) retries what a terminal job's own
clean-up (:func:`sm_images.imports.terminal.release_staging`) could not
delete, once the grace period has passed.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import datetime, timedelta
from typing import Final

from simple_module_db import finalize_session
from sqlalchemy import String, cast, delete, or_, select, update

from sm_images.imports.jobs import SYNC, TERMINAL, load, now, where
from sm_images.imports.lookup import get
from sm_images.imports.terminal import release_staging
from sm_images.intents import clear_intents, object_intent
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import JobStatus
from sm_images.pipeline.runtime import Runtime

__all__ = ["SWEEP_CAP", "delete_job", "reap_staging"]

logger = logging.getLogger(__name__)

SWEEP_CAP: Final = 200


async def delete_job(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> None:
    await get(runtime, tenant, job_id)
    async with runtime.session_factory() as db:
        await db.execute(
            update(ImportJob)
            .where(*where(tenant, job_id))
            .values(
                status=JobStatus.CANCELLED,
                generation=ImportJob.generation + 1,
                updated_at=now(),
            )
            .execution_options(**SYNC)
        )
        await finalize_session(db)
    async with runtime.session_factory() as db:
        row = await load(db, tenant, job_id)
        keys = [] if row is None else [k for k in {row.source_key, *(row.staged_keys or [])} if k]
        await finalize_session(db)
    async with object_intent(keys, session_factory=runtime.session_factory):
        pass
    async with runtime.session_factory() as db:
        await db.execute(
            delete(ImportItem)
            .where(ImportItem.job_id == job_id, ImportItem.tenant_id == tenant)
            .execution_options(**SYNC)
        )
        await db.execute(delete(ImportJob).where(*where(tenant, job_id)).execution_options(**SYNC))
        await finalize_session(db)
    if not keys:
        return
    try:
        await runtime.store().delete_keys(keys)
    except Exception:
        logger.warning("images.import.delete_objects_failed job=%s", job_id, exc_info=True)
        return
    with contextlib.suppress(Exception):
        async with runtime.session_factory() as db:
            await clear_intents(db, keys)
            await finalize_session(db)


async def reap_staging(runtime: Runtime, tenant: str, now_: datetime, grace_days: int) -> int:
    """Delete what terminal jobs older than the grace period still have staged
    (a finished base64 job with failures keeps its source until then)."""
    cutoff = now_ - timedelta(days=grace_days)
    stmt = (
        select(ImportJob.id)
        .where(
            ImportJob.tenant_id == tenant,
            ImportJob.status.in_(TERMINAL),
            or_(
                ImportJob.source_key.is_not(None),
                cast(ImportJob.staged_keys, String) != "[]",
            ),
            ImportJob.updated_at < cutoff,
        )
        .order_by(ImportJob.updated_at)
        .limit(SWEEP_CAP)
    )
    async with runtime.session_factory() as db:
        ids = list((await db.execute(stmt)).scalars())
        await finalize_session(db)
    done = 0
    for job_id in ids:
        done += await release_staging(runtime, tenant, job_id)
    return done
