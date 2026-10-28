"""``images.reconcile``: repair what at-most-once delivery can lose (decision 6).

A **platform enumerator**, never an unscoped worker. One narrow read under the
framework's ``all_tenants()`` lists the distinct tenant ids that own any images
row (deleted ones included - cleanup and stats still concern them); then each
tenant's work runs under ``tenant_context(t)`` in fresh sessions, with strict
isolation applying as in a request:

* step runs ``pending`` for longer than :data:`CUTOFF`, or ``running`` with an
  expired lease (a lost ``images.run_step`` message, a dead worker), are
  dispatched again - the claim's conditional ``UPDATE`` makes a duplicate
  harmless. A ``running`` row with *no* lease (an older writer) is first put
  back to ``pending``, or it would never expire;
* images whose processing cycle never concluded (a dispatch lost after
  ingest's commit, e.g. an empty pipeline) are dispatched, which decides
  ``ImageProcessed`` once;
* import items and jobs: counted and logged. Their runner tasks arrive with
  the import tasks; nothing is enqueued to a task name no worker registers;
* every live collection's stats are recomputed (the only way a box shrinks
  after deletes; there is no durable "touched" marker yet, so all of them,
  in batches).
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from simple_module_db import all_tenants, finalize_session, tenant_context
from sqlalchemy import and_, or_, select, update

from sm_images.models import Collection, Image, ImportItem, ImportJob, StepRun
from sm_images.models.enums import ItemStatus, JobStatus, StepStatus
from sm_images.pipeline.orchestrate import submit_dispatch
from sm_images.pipeline.runtime import Runtime
from sm_images.services import stats
from sm_images.tenancy import all_tenants as tagged
from sm_images.tenancy import valid_tenant

__all__ = ["CUTOFF", "reconcile_async", "reconcile_tenant", "tenants"]

logger = logging.getLogger(__name__)

CUTOFF = timedelta(minutes=5)
BATCH = 500
STATS_BATCH = 100
_ACTIVE_JOBS = (JobStatus.PENDING, JobStatus.STAGING, JobStatus.RUNNING)
_OWNERS = (Collection, Image, StepRun, ImportJob, ImportItem)


async def tenants(runtime: Runtime) -> list[str]:
    """Distinct tenant ids across images' tables, in one unscoped read session."""
    found: set[str] = set()
    with all_tenants():
        async with runtime.session_factory() as db:
            for model in _OWNERS:
                stmt = select(model.tenant_id).distinct().execution_options(include_deleted=True)
                found.update((await db.execute(tagged(stmt))).scalars())
            await finalize_session(db)
    return sorted(t for t in found if valid_tenant(t))


async def _ids(runtime: Runtime, stmt: Any, column: Any) -> list[Any]:
    """Every id ``stmt`` selects, in keyset batches."""
    out: list[Any] = []
    after = None
    while True:
        page = stmt.order_by(column).limit(BATCH)
        if after is not None:
            page = page.where(column > after)
        async with runtime.session_factory() as db:
            rows = list((await db.execute(page)).scalars())
            await finalize_session(db)
        out += rows
        if len(rows) < BATCH:
            return out
        after = rows[-1]


async def _repair_unleased(runtime: Runtime, tenant: str, cutoff: datetime) -> int:
    async with runtime.session_factory() as db:
        stmt = (
            update(StepRun)
            .where(
                StepRun.tenant_id == tenant,
                StepRun.status == StepStatus.RUNNING,
                StepRun.lease_expires_at.is_(None),
                or_(StepRun.started_at.is_(None), StepRun.started_at < cutoff),
            )
            .values(status=StepStatus.PENDING, lease_token=None)
            .returning(StepRun.id)
            .execution_options(synchronize_session=False)
        )
        n = len((await db.execute(stmt)).all())
        await finalize_session(db)
    return n


def _stranded(tenant: str, now: datetime, cutoff: datetime) -> Any:
    return (
        select(StepRun.image_id)
        .distinct()
        .where(
            StepRun.tenant_id == tenant,
            or_(
                and_(StepRun.status == StepStatus.PENDING, StepRun.created_at < cutoff),
                and_(StepRun.status == StepStatus.RUNNING, StepRun.lease_expires_at < now),
            ),
        )
    )


def _unconcluded(tenant: str, cutoff: datetime) -> Any:
    return select(Image.id).where(
        Image.tenant_id == tenant,
        Image.processed_generation < Image.processing_generation,
        Image.created_at < cutoff,
    )


async def _imports(runtime: Runtime, tenant: str, cutoff: datetime) -> tuple[int, int]:
    """Candidates only, until the import runner tasks exist to resume them."""
    jobs = select(ImportJob.id).where(
        ImportJob.tenant_id == tenant,
        ImportJob.status.in_(_ACTIVE_JOBS),
        or_(ImportJob.heartbeat_at.is_(None), ImportJob.heartbeat_at < cutoff),
    )
    items = (
        select(ImportItem.id)
        .join(ImportJob, ImportJob.id == ImportItem.job_id)
        .where(
            ImportItem.tenant_id == tenant,
            ImportItem.status == ItemStatus.PENDING,
            ImportJob.status.in_(_ACTIVE_JOBS),
        )
    )
    stale_jobs = await _ids(runtime, jobs, ImportJob.id)
    pending_items = await _ids(runtime, items, ImportItem.id)
    if stale_jobs or pending_items:
        logger.info(
            "images.reconcile.imports tenant=%s stale_jobs=%d pending_items=%d "
            "(no import runner registered yet; left in place)",
            tenant,
            len(stale_jobs),
            len(pending_items),
        )
    return len(stale_jobs), len(pending_items)


async def _recompute_stats(runtime: Runtime, tenant: str) -> int:
    ids = await _ids(
        runtime, select(Collection.id).where(Collection.tenant_id == tenant), Collection.id
    )
    for start in range(0, len(ids), STATS_BATCH):
        async with runtime.session_factory() as db:
            for collection_id in ids[start : start + STATS_BATCH]:
                await stats.recompute(db, collection_id)
            await finalize_session(db)
    return len(ids)


async def reconcile_tenant(runtime: Runtime, tenant: str, now: datetime) -> Counter[str]:
    """One tenant's recovery; the caller has bound ``tenant``."""
    cutoff = now - CUTOFF
    done: Counter[str] = Counter()
    done["repaired"] = await _repair_unleased(runtime, tenant, cutoff)
    stranded = await _ids(runtime, _stranded(tenant, now, cutoff), StepRun.image_id)
    unconcluded = await _ids(runtime, _unconcluded(tenant, cutoff), Image.id)
    for image_id in dict.fromkeys([*stranded, *unconcluded]):
        await submit_dispatch(runtime, tenant, image_id)
        done["dispatched"] += 1
    done["stale_jobs"], done["pending_items"] = await _imports(runtime, tenant, cutoff)
    done["collections"] = await _recompute_stats(runtime, tenant)
    return done


async def reconcile_async(runtime: Runtime, now: datetime) -> dict[str, int]:
    """Every tenant, each in its own scope. One tenant's failure is logged and
    does not stop the others."""
    total: Counter[str] = Counter()
    for tenant in await tenants(runtime):
        try:
            with tenant_context(tenant):
                total.update(await reconcile_tenant(runtime, tenant, now))
        except Exception:
            logger.exception("images.reconcile.tenant_failed tenant=%s", tenant)
            total["failed_tenants"] += 1
    return dict(total)
