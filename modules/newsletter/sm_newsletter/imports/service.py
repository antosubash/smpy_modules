"""Reading, mapping, queueing and discarding an import (R12; Tasks 6 and 8 consume this).

Every status change is one conditional Core ``UPDATE`` pinned to the id, the tenant and the
statuses it may leave, so two requests cannot both win. Nothing here commits.
"""

from __future__ import annotations

from simple_module_db import mark_written
from sm_records.contracts.newsletter_import import ImportTargets
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.access import MAX_BIG_ID, Roles, readable_lists, require_list
from sm_newsletter.core.errors import NotFound
from sm_newsletter.core.errors_import import ImportNotStaged, ImportRunning
from sm_newsletter.imports import mapping
from sm_newsletter.imports.constants import DONE, FAILED, QUEUED, STAGED
from sm_newsletter.models import ImportEntry, ImportJob

__all__ = ["discard", "get_import", "list_imports", "queue_apply", "set_mapping"]


async def get_import(
    session: AsyncSession, *, tenant_id: str, import_id: int, roles: Roles
) -> ImportJob:
    """The tenant's import, read fresh; :class:`NotFound` when there is none or its list is
    unreadable to this caller. An id outside the ``BIGINT`` key is a 404 before
    the query, never a driver error."""
    if not 0 < import_id <= MAX_BIG_ID:
        raise NotFound()
    stmt = (
        select(ImportJob)
        .where(ImportJob.id == import_id, ImportJob.tenant_id == tenant_id)
        .execution_options(populate_existing=True)
    )
    job = (await session.execute(stmt)).scalars().first()
    if job is None:
        raise NotFound()
    await require_list(session, tenant_id=tenant_id, list_type_key=job.list_type_key, roles=roles)
    return job


async def list_imports(
    session: AsyncSession, *, tenant_id: str, roles: Roles, limit: int = 20
) -> list[ImportJob]:
    """Newest first, the imports of lists this caller may read."""
    keys = await readable_lists(session, tenant_id=tenant_id, roles=roles)
    if not keys:
        return []
    stmt = (
        select(ImportJob)
        .where(ImportJob.tenant_id == tenant_id, ImportJob.list_type_key.in_(keys))
        .order_by(ImportJob.created_at.desc(), ImportJob.id.desc())
        .limit(limit)
        .execution_options(populate_existing=True)
    )
    return list((await session.execute(stmt)).scalars())


async def set_mapping(
    session: AsyncSession, *, tenant_id: str, job: ImportJob, raw: object, targets: ImportTargets
) -> ImportJob:
    """Replace the mapping of a staged import; :class:`ImportNotStaged` otherwise."""
    if job.status != STAGED:
        raise ImportNotStaged()
    checked = mapping.validate(raw, columns=job.columns, targets=targets, tags_found=job.tags_found)
    stmt = (
        update(ImportJob)
        .where(ImportJob.id == job.id, ImportJob.tenant_id == tenant_id, ImportJob.status == STAGED)
        .values(mapping=checked)
        .execution_options(synchronize_session=False)
    )
    if (await session.execute(stmt)).rowcount != 1:  # ty: ignore[unresolved-attribute]
        raise ImportNotStaged()
    mark_written(session)
    await session.refresh(job)
    return job


async def queue_apply(session: AsyncSession, *, tenant_id: str, job: ImportJob) -> ImportJob:
    """``staged`` or ``failed`` to ``queued``; :class:`ImportNotStaged` when the stored status is
    anything else (the object may be stale)."""
    stmt = (
        update(ImportJob)
        .where(
            ImportJob.id == job.id,
            ImportJob.tenant_id == tenant_id,
            ImportJob.status.in_((STAGED, FAILED)),
        )
        .values(status=QUEUED, error_code=None, lease_owner=None, lease_until=None)
        .execution_options(synchronize_session=False)
    )
    if (await session.execute(stmt)).rowcount != 1:  # ty: ignore[unresolved-attribute]
        raise ImportNotStaged()
    mark_written(session)
    await session.refresh(job)
    return job


async def discard(session: AsyncSession, *, tenant_id: str, job: ImportJob) -> None:
    """Delete a ``staged``, ``done`` or ``failed`` import and its rows;
    :class:`ImportRunning` for a ``queued`` or ``running`` one."""
    gone = await session.execute(
        delete(ImportJob)
        .where(
            ImportJob.id == job.id,
            ImportJob.tenant_id == tenant_id,
            ImportJob.status.in_((STAGED, DONE, FAILED)),
        )
        .execution_options(synchronize_session=False)
    )
    if gone.rowcount != 1:  # ty: ignore[unresolved-attribute]
        raise ImportRunning()
    await session.execute(
        delete(ImportEntry)
        .where(ImportEntry.import_id == job.id, ImportEntry.tenant_id == tenant_id)
        .execution_options(synchronize_session=False)
    )
    mark_written(session)
    session.expunge(job)
