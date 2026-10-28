"""Terminal moves of an import job: completion, failure, cancellation - and the
clean-up of its staged objects each of them triggers.

**Completion** is one compare-and-set - ``running``, every feature recorded
(``checkpoint_index >= total_count``) and no ``pending`` item - so exactly one
caller completes the job, and a paused or cancelled job is never resurrected.

**Staging.** A job that reaches a terminal state deletes its own staged objects
(:func:`release_staging`). If that fails it is logged, and the janitor retries
once the grace period has passed (:func:`sm_images.imports.recover.reap_staging`).
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from typing import Final

from simple_module_db import finalize_session
from sqlalchemy import exists, update

from sm_images.imports.jobs import ACTIVE, TERMINAL, load, now, returning_one, where
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime

__all__ = ["ERRORS_MAX", "fail", "finish", "release_staging", "try_complete"]

logger = logging.getLogger(__name__)

ERRORS_MAX: Final = 50


async def try_complete(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> bool:
    """Complete the job if everything is recorded and settled; one caller wins."""
    pending = exists().where(
        ImportItem.job_id == job_id,
        ImportItem.tenant_id == tenant,
        ImportItem.status == ItemStatus.PENDING,
    )
    stmt = (
        update(ImportJob)
        .where(
            *where(tenant, job_id),
            ImportJob.status == JobStatus.RUNNING,
            ImportJob.checkpoint_index >= ImportJob.total_count,
            ~pending,
        )
        .values(status=JobStatus.COMPLETED, heartbeat_at=now(), updated_at=now())
        .returning(ImportJob.id)
    )
    done = await returning_one(runtime, stmt) is not None
    if done:
        await release_staging(runtime, tenant, job_id)
    return done


async def finish(
    runtime: Runtime,
    tenant: str,
    job_id: uuid.UUID,
    generation: int,
    status: JobStatus,
    code: str | None = None,
) -> bool:
    """Move a job this runner owns to ``status`` (terminal), recording ``code``."""
    async with runtime.session_factory() as db:
        row = await load(db, tenant, job_id, lock=True)
        if row is None or row.generation != generation or row.status not in ACTIVE:
            await db.rollback()
            return False
        row.status = status
        row.updated_at = now()
        if code is not None:
            row.errors = [*(row.errors or []), {"code": code, "at": now().isoformat()}][
                -ERRORS_MAX:
            ]
        await finalize_session(db)
    if status in TERMINAL:
        await release_staging(runtime, tenant, job_id)
    return True


async def fail(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int, code: str
) -> bool:
    return await finish(runtime, tenant, job_id, generation, JobStatus.FAILED, code)


async def _delete_objects(runtime: Runtime, keys: list[str]) -> None:
    await runtime.store().delete_keys(keys)


async def release_staging(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, *, terminal_only: bool = True
) -> bool:
    """Delete the job's staged objects, then forget them. A failure is logged and
    left for the janitor; ``True`` when nothing is left staged."""
    async with runtime.session_factory() as db:
        row = await load(db, tenant, job_id)
        keys = [] if row is None else [k for k in {row.source_key, *(row.staged_keys or [])} if k]
        await finalize_session(db)
    if not keys:
        return True
    try:
        await _delete_objects(runtime, keys)
    except Exception:
        logger.warning("images.import.staging_delete_failed job=%s", job_id, exc_info=True)
        return False
    conds = [*where(tenant, job_id)]
    if terminal_only:
        conds.append(ImportJob.status.in_(TERMINAL))
    stmt = update(ImportJob).where(*conds).values(source_key=None, staged_keys=[])
    with contextlib.suppress(Exception):
        await returning_one(runtime, stmt.returning(ImportJob.id))
    return True
