"""Retry-failed: ``failed`` items back to work, once each.

Items are reset in keyset chunks of :data:`RESET_CHUNK`, each chunk one short
transaction that moves ``failed`` to ``pending`` (a compare-and-set, so a
double click resets an item once) and decrements the failed counter by exactly
the rows it moved. The job is reopened, and only then is work handed on:
downloads for URL items, a new runner generation for base64 items (whose bytes
are only in the source, so it must still be staged).
"""

from __future__ import annotations

import uuid
from typing import Final

from simple_module_db import finalize_session
from sqlalchemy import select, update

from sm_images.imports import jobs
from sm_images.imports import launch as handoff
from sm_images.imports.jobs import ACTIVE, TERMINAL, now, where
from sm_images.imports.lookup import conflict, get
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import ImportKind, ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime

__all__ = ["RESET_CHUNK", "pending_url_items", "reset_failed", "retry_failed"]

RESET_CHUNK: Final = 1000
_SYNC: Final = {"synchronize_session": False}


async def pending_url_items(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> None:
    """Hand out every pending URL item again, in keyset pages."""
    after = 0
    while True:
        stmt = (
            select(ImportItem.id)
            .where(
                ImportItem.job_id == job_id,
                ImportItem.tenant_id == tenant,
                ImportItem.status == ItemStatus.PENDING,
                ImportItem.id > after,
            )
            .order_by(ImportItem.id)
            .limit(RESET_CHUNK)
        )
        async with runtime.session_factory() as db:
            ids = [int(i) for i in (await db.execute(stmt)).scalars()]
            await finalize_session(db)
        if not ids:
            return
        await handoff.launch_downloads(runtime, tenant, job_id, ids)
        after = ids[-1]


async def _reset_chunk(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, after: int, url: bool, count: bool
):
    page = (
        select(ImportItem.id)
        .where(
            ImportItem.job_id == job_id,
            ImportItem.tenant_id == tenant,
            ImportItem.status == ItemStatus.FAILED,
            ImportItem.id > after,
        )
        .order_by(ImportItem.id)
        .limit(RESET_CHUNK)
    )
    if url:
        page = page.where(ImportItem.url.is_not(None))
    async with runtime.session_factory() as db:
        ids = [int(i) for i in (await db.execute(page)).scalars()]
        moved: list[int] = []
        if ids:
            stmt = (
                update(ImportItem)
                .where(
                    ImportItem.id.in_(ids),
                    ImportItem.tenant_id == tenant,
                    ImportItem.status == ItemStatus.FAILED,
                )
                .values(status=ItemStatus.PENDING, attempts=0, last_error=None, updated_at=now())
                .returning(ImportItem.id)
                .execution_options(**_SYNC)
            )
            moved = [int(i) for i in (await db.execute(stmt)).scalars()]
            if count:
                await jobs.bump(db, tenant, job_id, {ItemStatus.FAILED: -len(moved)})
        await finalize_session(db)
    return ids, moved


async def reset_failed(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, *, url: bool, count: bool = True
) -> list[int]:
    """Every ``failed`` item (with a URL, for URL jobs) back to ``pending``; the
    ids moved. ``count`` decrements the failed counter by as many."""
    reset: list[int] = []
    after = 0
    while True:
        ids, moved = await _reset_chunk(runtime, tenant, job_id, after, url, count)
        reset += moved
        if len(ids) < RESET_CHUNK:
            return reset
        after = ids[-1]


async def retry_failed(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> ImportJob:
    row = await get(runtime, tenant, job_id)
    url = row.kind is ImportKind.GEOJSON_URL
    if row.status is JobStatus.PAUSED:
        raise conflict("job_paused", "Resume the import before retrying its failures")
    if not url and row.source_key is None:
        raise conflict("source_gone", "The source of this import is no longer stored")
    if url and row.status not in ACTIVE and row.checkpoint_index < row.total_count:
        raise conflict(
            "job_incomplete", "This import never finished reading its source; restart it"
        )
    reset = await reset_failed(runtime, tenant, job_id, url=url)
    if not reset:
        return await get(runtime, tenant, job_id)
    reopen = {"heartbeat_at": now(), "updated_at": now()}
    if url:
        reopen["status"] = JobStatus.RUNNING
    else:
        reopen |= {"status": JobStatus.PENDING, "generation": ImportJob.generation + 1}
    stmt = (
        update(ImportJob)
        .where(*where(tenant, job_id), ImportJob.status.in_((*ACTIVE, *TERMINAL)))
        .values(**reopen)
        .returning(ImportJob.generation)
    )
    found = await jobs.returning_one(runtime, stmt)
    if found is not None:
        if url:
            await handoff.launch_downloads(runtime, tenant, job_id, reset)
        else:
            await handoff.launch_runner(runtime, tenant, job_id, int(found[0]))
    return await get(runtime, tenant, job_id)
