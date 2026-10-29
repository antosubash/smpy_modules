"""The regroup job's runner: bounded chunks, each in its own transaction.

One chunk = read the next images after the cursor, plan them, resolve their
groups, write the assignments and advance the job's cursor and counters - all
in one transaction fenced on the job's generation (:func:`jobs.advance`). A
runner that was replaced (a reconcile claim, a cancel) loses that fence, rolls
the chunk back and stops; the job's owner can have lost the edit right too, in
which case the job is cancelled (``access_revoked``). A runner that dies
leaves the job at its last committed chunk; reconcile claims it and a new
runner carries on from the cursor.
"""

from __future__ import annotations

import logging
import uuid

from simple_module_db import finalize_session
from sqlalchemy import select

from sm_images import constants
from sm_images.imports.access import ACCESS_REVOKED, MANAGE, manager_active, shared_edit
from sm_images.models import Collection
from sm_images.pipeline.runtime import Runtime
from sm_images.regroup import jobs
from sm_images.services import regroup as plan
from sm_images.services import regroup_write as write

__all__ = ["may_edit", "run_regroup"]

logger = logging.getLogger(__name__)
COLLECTION_GONE = "collection_gone"


async def may_edit(runtime: Runtime, tenant: str, job: jobs.Snap) -> bool:
    """Whether the job's ``run_as`` still holds edit on its collection (the
    import jobs' re-check, ``imports.access``). A job with no ``run_as`` is not checked."""
    if job.run_as is None:
        return True
    stmt = select(Collection.owner_id).where(
        Collection.id == job.collection_id, Collection.tenant_id == tenant
    )
    async with runtime.session_factory() as db:
        owner = (await db.execute(stmt)).scalar_one_or_none()
        shared = None
        if owner is not None and owner != job.run_as:
            shared = (await db.execute(shared_edit(job.run_as, job.collection_id))).first()
        await finalize_session(db)
    if owner is None or owner == job.run_as or shared is not None:
        return True  # a missing collection is reported by the chunk itself
    if job.access_basis == MANAGE:
        return await manager_active(runtime, tenant, job.run_as)
    return False


async def _chunk(runtime: Runtime, tenant: str, job: jobs.Snap, generation: int) -> bool:
    """Run one chunk; ``False`` when the job is done (no images left) or this
    runner no longer owns it."""
    async with runtime.session_factory() as db:
        coll = (
            await db.execute(
                select(Collection).where(
                    Collection.id == job.collection_id, Collection.tenant_id == tenant
                )
            )
        ).scalar_one_or_none()
        if coll is None:
            await db.rollback()
            await jobs.finish(
                runtime, tenant, job.id, generation, status="failed", error_code=COLLECTION_GONE
            )
            return False
        rows = await plan.fetch_chunk(db, tenant, coll.id, job.cursor, constants.REGROUP_CHUNK)
        if not rows:
            await db.rollback()
            await jobs.finish(runtime, tenant, job.id, generation)
            return False
        compiled = plan.compile_or_422(job.pattern)
        chunk = await plan.derive_chunk(compiled, list(coll.group_roles or []), rows, job.reassign)
        tally = chunk.tally
        tally.assigned, created, existing = await write.settle(
            db,
            tenant,
            coll.id,
            chunk.changes,
            reassign=job.reassign,
            dry_run=job.dry_run,
            since=job.began,
        )
        if not job.dry_run:  # a preview would count a group once per chunk it appears in
            tally.groups_created, tally.groups_existing = created, existing
        cursor = (rows[-1][1], rows[-1][0])
        if not await jobs.advance(db, tenant, job, generation, cursor, tally):
            await db.rollback()
            return False
        await finalize_session(db)
    return True


async def run_regroup(runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int) -> int:
    """Carry job ``job_id`` on from its cursor as the runner of ``generation``;
    returns the chunks committed."""
    chunks = 0
    while True:
        job = await jobs.snapshot(runtime, tenant, job_id)
        if job is None or job.generation != generation:
            return chunks  # deleted, or a newer runner owns it
        if not await may_edit(runtime, tenant, job):
            if await jobs.cancel(runtime, tenant, job_id, error_code=ACCESS_REVOKED):
                logger.info("images.regroup.access_revoked job=%s", job_id)
            return chunks
        if not await _chunk(runtime, tenant, job, generation):
            return chunks
        chunks += 1
