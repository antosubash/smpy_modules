"""Terminal moves of an import job: completion, failure, cancellation - and the
clean-up of its staged source each of them may trigger.

**Completion** is one compare-and-set - ``running``, every feature recorded
(``checkpoint_index >= total_count``) and no ``pending`` item - so exactly one
caller completes the job, and a paused or cancelled job is never resurrected.

**Staging** (:func:`release_staging`, for the generation whose transition
asked for it, so a late clean-up never acts on a newer generation). A URL
job's items carry every URL, so a finished one never needs its source again
and deletes it at once. A base64
(or ZIP) job's image bytes live only in the source: one that finished with failed items
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
from datetime import datetime
from typing import Any, Final

from simple_module_db import finalize_session
from sqlalchemy import and_, exists, not_, or_, update

from sm_images.imports.jobs import ACTIVE, SYNC, TERMINAL, load, now, returning_one, where
from sm_images.intents import clear_intents, object_intent
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import ImportKind, ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime

__all__ = ["ERRORS_MAX", "fail", "finish", "release_staging", "try_complete"]

logger = logging.getLogger(__name__)

ERRORS_MAX: Final = 50


async def try_complete(runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int) -> bool:
    """Complete the job if everything is recorded and settled - for the caller's
    ``generation`` only (a stale runner or download never completes a newer
    run's job); one caller wins."""
    pending = exists().where(
        ImportItem.job_id == job_id,
        ImportItem.tenant_id == tenant,
        ImportItem.status == ItemStatus.PENDING,
    )
    stmt = (
        update(ImportJob)
        .where(
            *where(tenant, job_id),
            ImportJob.generation == generation,
            ImportJob.status == JobStatus.RUNNING,
            ImportJob.checkpoint_index >= ImportJob.total_count,
            ~pending,
        )
        .values(status=JobStatus.COMPLETED, heartbeat_at=now(), updated_at=now())
        .returning(ImportJob.generation)
    )
    found = await returning_one(runtime, stmt)
    if found is None:
        return False
    await release_staging(runtime, tenant, job_id, int(found[0]))
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
    await release_staging(runtime, tenant, job_id, generation)
    return True


async def fail(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int, code: str
) -> bool:
    return await finish(runtime, tenant, job_id, generation, JobStatus.FAILED, code)


async def _delete_objects(runtime: Runtime, keys: list[str]) -> None:
    await runtime.store().delete_keys(keys)


def _eligible(grace_cutoff: datetime | None) -> Any:
    """SQL for "may delete its source now": not a source a finished base64 or
    ZIP job keeps for retry-failed - or, for the janitor, kept past the grace period."""
    kept = and_(
        ImportJob.kind.in_((ImportKind.GEOJSON_BASE64, ImportKind.ZIP)),
        ImportJob.status == JobStatus.COMPLETED,
        ImportJob.failed_count > 0,
    )
    if grace_cutoff is None:
        return not_(kept)
    return or_(not_(kept), ImportJob.updated_at < grace_cutoff)


async def release_staging(
    runtime: Runtime,
    tenant: str,
    job_id: uuid.UUID,
    generation: int,
    *,
    grace_cutoff: datetime | None = None,
) -> bool:
    """Detach, then delete, the staged keys of a terminal job **as of
    ``generation``** - the generation whose transition asked for it. A job a
    newer generation owns, or one not eligible (:func:`_eligible`), is left
    alone. ``True`` when this call detached the keys (or found none)."""
    async with runtime.session_factory() as db:
        row = await load(db, tenant, job_id)
        found = None
        if row is not None and row.status in TERMINAL and row.generation == generation:
            keys = [k for k in dict.fromkeys([row.source_key, *(row.staged_keys or [])]) if k]
            found = (keys, row.source_key)
        await finalize_session(db)
    if found is None:
        return False
    keys, source_key = found
    if not keys:
        return True
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
            _eligible(grace_cutoff),
        )
        .values(source_key=None, staged_keys=[])
        .returning(ImportJob.id)
        .execution_options(**SYNC)
    )
    if await returning_one(runtime, stmt) is None:
        return False  # reopened, retained, or a newer generation: not this call's
    try:
        await _delete_objects(runtime, keys)
    except Exception:
        logger.warning("images.import.staging_delete_failed job=%s", job_id, exc_info=True)
        return True  # detached; the intents let the janitor finish the delete
    async with runtime.session_factory() as db:
        await clear_intents(db, keys)
        await finalize_session(db)
    return True
