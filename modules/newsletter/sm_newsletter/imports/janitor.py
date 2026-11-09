"""The hourly import janitor (R6, R14, D2): expire what nobody applied, relaunch lost work.

One narrow read with no tenant bound (``all_tenants()``) of ``(tenant, id, status)`` for:

* ``staged`` jobs older than ``STAGED_TTL`` (from ``created_at``) and ``failed`` jobs older
  than it from when they failed (``finished_at``, else ``created_at``): deleted, their staged
  rows with them - staged rows hold addresses;
* ``queued`` jobs older than ``LEASE`` from ``created_at``: the message was lost (a job
  staged long ago and queued just now is relaunched at once; the claim answers ``busy``);
* ``running`` jobs whose lease was released (``lease_owner IS NULL``) more than ``LEASE``
  ago - a slice whose follow-up message was lost (D2) - or whose owned lease has run out.

Then per tenant, under ``tenant_scope``, the writes: delete the expired, send the rest back
through ``run_import``. A relaunch of a job somebody still runs is harmless: the claim
answers ``busy``. Counts only; nothing here logs a value.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from itertools import groupby

from simple_module_db import finalize_session
from simple_module_db.tenancy import all_tenants as framework_all_tenants
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import tenancy
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.imports.constants import FAILED, LEASE, QUEUED, RUNNING, STAGED, STAGED_TTL
from sm_newsletter.models import ImportEntry, ImportJob

__all__ = ["janitor_async"]

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]


def _expirable(cutoff: datetime):
    """``staged`` from ``created_at``, ``failed`` from when it failed (F1), before ``cutoff``:
    the candidate read and the guarded delete both decide by it, with the same cutoff."""
    return or_(
        and_(ImportJob.status == STAGED, ImportJob.created_at < cutoff),
        and_(
            ImportJob.status == FAILED,
            func.coalesce(ImportJob.finished_at, ImportJob.created_at) < cutoff,
        ),
    )


def _candidates(now: datetime):
    stale = now - LEASE
    return select(ImportJob.tenant_id, ImportJob.id, ImportJob.status).where(
        or_(
            _expirable(now - STAGED_TTL),
            and_(ImportJob.status == QUEUED, ImportJob.created_at < stale),
            and_(
                ImportJob.status == RUNNING,
                or_(
                    and_(
                        ImportJob.lease_owner.is_(None),  # ty: ignore[unresolved-attribute]
                        ImportJob.lease_until < stale,
                    ),
                    and_(
                        ImportJob.lease_owner.is_not(None),  # ty: ignore[unresolved-attribute]
                        ImportJob.lease_until < now,
                    ),
                ),
            ),
        )
    )


async def janitor_async(factory: SessionFactory, *, now: datetime) -> dict[str, int]:
    """``{"expired", "relaunched", "failed"}``; run with no tenant bound."""
    from sm_newsletter.imports.launch import enqueue

    with framework_all_tenants():
        async with factory() as session:
            found = (await session.execute(tenancy.all_tenants(_candidates(now)))).all()
            await finalize_session(session)
    summary = {"expired": 0, "relaunched": 0, "failed": 0}
    for tenant_id, group in groupby(sorted(found), key=lambda r: r[0]):
        rows = list(group)
        with tenant_scope(tenant_id):
            expired = [r[1] for r in rows if r[2] in (STAGED, FAILED)]
            if expired:
                try:
                    summary["expired"] += await _expire(
                        factory, tenant_id, expired, now - STAGED_TTL
                    )
                except Exception as exc:
                    logger.warning(
                        "newsletter import janitor: expiring failed: %s", type(exc).__name__
                    )
                    summary["failed"] += len(expired)
            for _, import_id, status in rows:
                if status in (STAGED, FAILED):
                    continue
                try:
                    enqueue(tenant_id, import_id)
                    summary["relaunched"] += 1
                except Exception as exc:
                    logger.warning(
                        "newsletter import janitor: relaunching %s failed: %s",
                        import_id,
                        type(exc).__name__,
                    )
                    summary["failed"] += 1
    return summary


async def _expire(factory: SessionFactory, tenant_id: str, ids: list[int], cutoff: datetime) -> int:
    """Delete the jobs still expirable by ``cutoff`` first, then the rows of those jobs only;
    how many jobs went.

    The guard repeats the candidate read's predicate with its cutoff: a ``queue_apply`` that
    won the race since that read keeps its job and its rows (one that comes later finds
    nothing, 409), and so does a job retried and failed again since (freshly timed).
    """
    async with factory() as session:
        gone = await session.execute(
            delete(ImportJob)
            .where(
                ImportJob.tenant_id == tenant_id,
                ImportJob.id.in_(ids),  # ty: ignore[unresolved-attribute]
                _expirable(cutoff),
            )
            .returning(ImportJob.id)
            .execution_options(synchronize_session=False)
        )
        deleted = [r[0] for r in gone.all()]
        if deleted:
            await session.execute(
                delete(ImportEntry)
                .where(
                    ImportEntry.tenant_id == tenant_id,
                    ImportEntry.import_id.in_(deleted),  # ty: ignore[unresolved-attribute]
                )
                .execution_options(synchronize_session=False)
            )
        await finalize_session(session)
        return len(deleted)
