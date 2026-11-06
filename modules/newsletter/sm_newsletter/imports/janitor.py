"""The hourly import janitor (R6, R14, D2): expire what nobody applied, relaunch lost work.

One narrow read with no tenant bound (``all_tenants()``) of ``(tenant, id, status)`` for:

* ``staged`` or ``failed`` jobs older than ``STAGED_TTL``: deleted (their staged rows with
  them) - staged rows hold addresses;
* ``queued`` jobs older than ``LEASE``: the message was lost;
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
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import tenancy
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.imports.constants import FAILED, LEASE, QUEUED, RUNNING, STAGED, STAGED_TTL
from sm_newsletter.models import ImportEntry, ImportJob

__all__ = ["janitor_async"]

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]


def _candidates(now: datetime):
    stale = now - LEASE
    return select(ImportJob.tenant_id, ImportJob.id, ImportJob.status).where(
        or_(
            and_(
                ImportJob.status.in_((STAGED, FAILED)),  # ty: ignore[unresolved-attribute]
                ImportJob.created_at < now - STAGED_TTL,
            ),
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
                    await _expire(factory, tenant_id, expired)
                    summary["expired"] += len(expired)
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


async def _expire(factory: SessionFactory, tenant_id: str, ids: list[int]) -> None:
    async with factory() as session:
        for stmt in (
            delete(ImportEntry).where(
                ImportEntry.tenant_id == tenant_id,
                ImportEntry.import_id.in_(ids),  # ty: ignore[unresolved-attribute]
            ),
            delete(ImportJob).where(
                ImportJob.tenant_id == tenant_id,
                ImportJob.id.in_(ids),  # ty: ignore[unresolved-attribute]
                ImportJob.status.in_((STAGED, FAILED)),  # ty: ignore[unresolved-attribute]
            ),
        ):
            await session.execute(stmt.execution_options(synchronize_session=False))
        await finalize_session(session)
