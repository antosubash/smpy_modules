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
* placeholder skips (``not_installed``, ``disabled``) whose step is enabled
  and installed again are dispatched, which reopens them
  (:mod:`sm_images.placeholders`);
* images whose processing cycle never concluded (a dispatch lost after
  ingest's commit, e.g. an empty pipeline) are dispatched, which decides
  ``ImageProcessed`` once;
* import jobs whose runner went silent are reclaimed (a new generation) and
  ``images.import_geojson`` is launched again; URL items left ``pending`` are
  handed to ``images.download_items`` again (:mod:`sm_images.imports.recover`);
* unfinished collection restarts whose heartbeat is stale are resumed (on the
  imports queue in broker mode, inline when eager);
* regroup jobs of big collections whose heartbeat is stale are claimed (a new
  generation) and relaunched from their cursor (:mod:`sm_images.regroup`);
* group prompt runs requested longer than :data:`CUTOFF` ago and never
  claimed, or claimed under an expired lease, are dispatched again
  (:func:`sm_images.ai.group_request.recover_group_runs`);
* storage-gauge settlements left pending in the outbox (billing was down, a
  worker died after the commit) are retried in bounded pages, each op after
  its backoff (:func:`sm_images.billing_ops.settle`), and an image that lost
  a committed swap is reconciled (:func:`sm_images.billing_repair.repair`);
* every live collection's stats are recomputed (the only way a box shrinks
  after deletes; there is no durable "touched" marker yet, so all of them,
  in batches);
* maps that are due and not claimed - a lost ``images.build_map``, a claim
  that expired, a withdrawn map - are requested again
  (:func:`sm_images.map.recover.reconcile_maps`).
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from simple_module_db import all_tenants, finalize_session, tenant_context
from sqlalchemy import and_, or_, select, update

from sm_images import billing_ops, billing_repair
from sm_images.ai.group_request import recover_group_runs
from sm_images.imports.recover import recover_imports
from sm_images.map.recover import reconcile_maps
from sm_images.models import (
    BillingOp,
    Collection,
    Image,
    ImportItem,
    ImportJob,
    PipelineRestart,
    RegroupJob,
    StepRun,
)
from sm_images.models.enums import StepStatus
from sm_images.pipeline.orchestrate import submit_dispatch
from sm_images.pipeline.runtime import Runtime
from sm_images.placeholders import reopenable_images
from sm_images.regroup import control as regroup_control
from sm_images.regroup import jobs as regroup_jobs
from sm_images.services import stats
from sm_images.tenancy import all_tenants as tagged
from sm_images.tenancy import valid_tenant

__all__ = ["CUTOFF", "reconcile_async", "reconcile_tenant", "tenants"]

logger = logging.getLogger(__name__)

CUTOFF = timedelta(minutes=5)
BATCH = 500
STATS_BATCH = 100
_OWNERS = (
    Collection,
    Image,
    StepRun,
    ImportJob,
    ImportItem,
    PipelineRestart,
    RegroupJob,
    BillingOp,
)


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
    """Runs of live images in live collections only: dead work is not re-sent."""
    return (
        select(StepRun.image_id)
        .distinct()
        .join(Image, Image.id == StepRun.image_id)
        .join(Collection, Collection.id == Image.collection_id)
        .where(
            StepRun.tenant_id == tenant,
            Image.tenant_id == tenant,
            Image.is_deleted.is_(False),
            Collection.is_deleted.is_(False),
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


async def _restarts(runtime: Runtime, tenant: str, now: datetime, cutoff: datetime) -> int:
    """Resume restarts nobody is advancing; claim each by moving its heartbeat."""
    stale = (
        update(PipelineRestart)
        .where(
            PipelineRestart.tenant_id == tenant,
            PipelineRestart.finished_at.is_(None),
            or_(PipelineRestart.heartbeat_at.is_(None), PipelineRestart.heartbeat_at < cutoff),
        )
        .values(heartbeat_at=now)
        .returning(PipelineRestart.id, PipelineRestart.collection_id, PipelineRestart.scope)
        .execution_options(synchronize_session=False)
    )
    async with runtime.session_factory() as db:
        rows = list((await db.execute(stale)).all())
        await finalize_session(db)
    for restart_id, collection_id, scope in rows:
        if runtime.is_eager():
            from sm_images.pipeline.restart import resume_restart

            await resume_restart(runtime, tenant, restart_id)
            continue
        from background_tasks.tenant_context import TENANT_HEADER

        from sm_images.task_config import QUEUE_IMPORTS
        from sm_images.tasks import restart_collection

        restart_collection.s(str(collection_id), scope, str(restart_id)).apply_async(
            queue=QUEUE_IMPORTS, headers={TENANT_HEADER: tenant}
        )
    return len(rows)


async def _regroups(runtime: Runtime, tenant: str, cutoff: datetime) -> int:
    """Relaunch regroup jobs nobody is advancing (a new generation each)."""
    claimed = await regroup_control.claim_stale(runtime, tenant, cutoff)
    for job_id, generation in claimed:
        await regroup_jobs.launch(runtime, tenant, job_id, generation)
    return len(claimed)


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
    reopen = await reopenable_images(runtime, tenant, partial(_ids, runtime))
    done["reopened"] = len(reopen)
    for image_id in dict.fromkeys([*stranded, *unconcluded, *reopen]):
        await submit_dispatch(runtime, tenant, image_id)
        done["dispatched"] += 1
    done["restarts"] = await _restarts(runtime, tenant, now, cutoff)
    done["regroups"] = await _regroups(runtime, tenant, cutoff)
    done["import_jobs"], done["import_items"] = await recover_imports(runtime, tenant, cutoff)
    done["group_runs"] = await recover_group_runs(runtime, tenant, now, cutoff)
    done["billing_ops"] = await billing_ops.settle(runtime.session_factory, tenant, now=now)
    done["billing_repaired"] = await billing_repair.repair(runtime.session_factory, tenant, now)
    done["collections"] = await _recompute_stats(runtime, tenant)
    done["maps"] = await reconcile_maps(runtime, tenant, now)
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
