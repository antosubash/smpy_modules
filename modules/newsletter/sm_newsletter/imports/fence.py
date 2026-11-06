"""The import's lease (R13, D2, D3): the claim, and the one guard every later state write passes.

:func:`claim` takes the job with a conditional ``UPDATE`` for a fresh owner. After that, every
write to the job - the tags step, each batch's counters and lease renewal, completion, the
release and the failure - goes through :func:`fenced`, an ``UPDATE`` that matches only while
``lease_owner`` is this owner and ``status`` is ``running``. A zero-row match raises
:class:`LeaseLost`: the caller rolls back, so writes to other tables in the same transaction
(records, suppressions, row outcomes) are committed only if the guard matched. Nothing here
commits.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from simple_module_db import mark_written
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.imports.constants import LEASE, QUEUED, RUNNING
from sm_newsletter.models import ImportJob

__all__ = ["LeaseLost", "claim", "fenced"]


class LeaseLost(Exception):  # noqa: N818 - the state it reports
    """The guard matched no row: another worker owns the job, or it left ``running``."""


async def claim(
    session: AsyncSession, *, tenant_id: str, import_id: int, owner: str, now: datetime
) -> Literal["claimed", "busy", "gone"]:
    """Take a ``queued`` or ``running`` job nobody holds (or whose lease ran out)."""
    stmt = (
        update(ImportJob)
        .where(
            ImportJob.id == import_id,
            ImportJob.tenant_id == tenant_id,
            ImportJob.status.in_((QUEUED, RUNNING)),  # ty: ignore[unresolved-attribute]
            or_(ImportJob.lease_owner.is_(None), ImportJob.lease_until < now),  # ty: ignore[unresolved-attribute]
        )
        .values(
            status=RUNNING,
            lease_owner=owner,
            lease_until=now + LEASE,
            started_at=func.coalesce(ImportJob.started_at, now),
        )
        .execution_options(synchronize_session=False)
    )
    if (await session.execute(stmt)).rowcount == 1:  # ty: ignore[unresolved-attribute]
        mark_written(session)
        return "claimed"
    status = (
        await session.execute(
            select(ImportJob.status).where(
                ImportJob.id == import_id, ImportJob.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    return "busy" if status in (QUEUED, RUNNING) else "gone"


async def fenced(
    session: AsyncSession, *, tenant_id: str, import_id: int, owner: str, values: dict[str, Any]
) -> None:
    """``UPDATE`` the job while ``owner`` holds it; :class:`LeaseLost` otherwise."""
    stmt = (
        update(ImportJob)
        .where(
            ImportJob.id == import_id,
            ImportJob.tenant_id == tenant_id,
            ImportJob.lease_owner == owner,
            ImportJob.status == RUNNING,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if (await session.execute(stmt)).rowcount != 1:  # ty: ignore[unresolved-attribute]
        raise LeaseLost
    mark_written(session)
