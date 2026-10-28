"""Terminal moves of an import job: completion, failure, cancellation - and the
clean-up of its staged source each of them may trigger.

**Completion** is one compare-and-set - ``running``, every feature recorded
(``checkpoint_index >= total_count``) and no ``pending`` item - so exactly one
caller completes the job, and a paused or cancelled job is never resurrected.

**Staging** (:func:`release_staging`). A URL job's items carry every URL, so a
finished one never needs its source again and deletes it at once. A base64
job's image bytes live only in the source: one that finished with failed items
keeps it, so retry-failed can re-read them, until the janitor's grace period
(:func:`sm_images.imports.cleanup.reap_staging`); one with no failures deletes
it at once. Failed and cancelled jobs delete theirs.

The keys are **detached before** a byte is deleted: their intents are written,
then one conditional ``UPDATE`` (still terminal, same generation, same source)
empties the job's references. A restart or retry that reopened the job in the
meantime wins - nothing of its source is touched - and a key once detached is
never named by the job again. Only the detach winner deletes; a failed delete
leaves the intents for the janitor's intent pass.
"""

from __future__ import annotations

import logging
import uuid
from typing import Final

from simple_module_db import finalize_session
from sqlalchemy import exists, update

from sm_images.imports.jobs import ACTIVE, SYNC, TERMINAL, load, now, returning_one, where
from sm_images.intents import clear_intents, object_intent
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import ImportKind, ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime

__all__ = ["ERRORS_MAX", "fail", "finish", "keeps_source", "release_staging", "try_complete"]

logger = logging.getLogger(__name__)

ERRORS_MAX: Final = 50


def keeps_source(kind: ImportKind, status: JobStatus, failed_count: int) -> bool:
    """A finished base64 job with failures keeps its source for retry-failed."""
    return kind is ImportKind.GEOJSON_BASE64 and status is JobStatus.COMPLETED and failed_count > 0


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
        .returning(ImportJob.kind, ImportJob.failed_count)
    )
    found = await returning_one(runtime, stmt)
    if found is None:
        return False
    if not keeps_source(found[0], JobStatus.COMPLETED, found[1]):
        await release_staging(runtime, tenant, job_id)
    return True


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
            entry = {"code": code, "at": now().isoformat()}
            row.errors = [*(row.errors or []), entry][-ERRORS_MAX:]
        await finalize_session(db)
    await release_staging(runtime, tenant, job_id)
    return True


async def fail(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int, code: str
) -> bool:
    return await finish(runtime, tenant, job_id, generation, JobStatus.FAILED, code)


async def _delete_objects(runtime: Runtime, keys: list[str]) -> None:
    await runtime.store().delete_keys(keys)


async def release_staging(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> bool:
    """Detach a terminal job's staged keys, then delete them. ``True`` when the
    job names no staged object any more."""
    async with runtime.session_factory() as db:
        row = await load(db, tenant, job_id)
        found = None
        if row is not None and row.status in TERMINAL:
            keys = [k for k in dict.fromkeys([row.source_key, *(row.staged_keys or [])]) if k]
            found = (keys, row.generation, row.source_key)
        await finalize_session(db)
    if found is None or not found[0]:
        return found is not None
    keys, generation, source_key = found
    async with object_intent(keys, session_factory=runtime.session_factory):
        pass
    same_source = (
        ImportJob.source_key.is_(None) if source_key is None else ImportJob.source_key == source_key
    )
    stmt = (
        update(ImportJob)
        .where(
            *where(tenant, job_id),
            ImportJob.status.in_(TERMINAL),
            ImportJob.generation == generation,
            same_source,
        )
        .values(source_key=None, staged_keys=[])
        .returning(ImportJob.id)
        .execution_options(**SYNC)
    )
    if await returning_one(runtime, stmt) is None:
        return False  # reopened meantime: its source is in use again
    try:
        await _delete_objects(runtime, keys)
    except Exception:
        logger.warning("images.import.staging_delete_failed job=%s", job_id, exc_info=True)
        return True  # detached; the intents let the janitor finish the delete
    async with runtime.session_factory() as db:
        await clear_intents(db, keys)
        await finalize_session(db)
    return True
