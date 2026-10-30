"""Reads: a job for a control (and the refusals controls answer with), the
live collection a run works in, and where a run resumes."""

from __future__ import annotations

import uuid

from simple_module_db import finalize_session
from sqlalchemy import func, select

from sm_images.core.errors import Conflict, NotFound
from sm_images.imports.jobs import JobSnap, load
from sm_images.models import Collection, ImportItem, ImportJob
from sm_images.models.enums import ImportKind, ItemStatus
from sm_images.pipeline.runtime import Runtime

__all__ = ["conflict", "get", "live_collection", "resume_index"]


def conflict(code: str, detail: str) -> Conflict:
    """A 409 whose ``code`` tells the console which control was refused and why."""
    return Conflict(detail, code=code)


async def get(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> ImportJob:
    """The job in ``tenant``, or 404."""
    async with runtime.session_factory() as db:
        row = await load(db, tenant, job_id)
        if row is not None:
            db.expunge(row)  # a detached snapshot: the commit must not expire it
        await finalize_session(db)
    if row is None:
        raise NotFound("Import job not found")
    return row


async def live_collection(runtime: Runtime, tenant: str, collection_id: uuid.UUID):
    async with runtime.session_factory() as db:
        stmt = select(Collection).where(
            Collection.id == collection_id, Collection.tenant_id == tenant
        )
        found = (await db.execute(stmt)).scalar_one_or_none()
        if found is not None:
            db.expunge(found)  # a loaded, detached snapshot: the commit must not expire it
        await finalize_session(db)
    return found


async def resume_index(runtime: Runtime, tenant: str, job: JobSnap) -> int:
    """Where streaming restarts: the checkpoint, or - base64 and ZIP, whose image
    bytes live only in the source - the first recorded item still waiting for one."""
    if job.kind not in (ImportKind.GEOJSON_BASE64, ImportKind.ZIP):
        return job.checkpoint_index
    stmt = select(func.min(ImportItem.feature_index)).where(
        ImportItem.job_id == job.id,
        ImportItem.tenant_id == tenant,
        ImportItem.status == ItemStatus.PENDING,
        ImportItem.image_id.is_(None),
    )
    async with runtime.session_factory() as db:
        first = (await db.execute(stmt)).scalar()
        await finalize_session(db)
    return job.checkpoint_index if first is None else min(first, job.checkpoint_index)
