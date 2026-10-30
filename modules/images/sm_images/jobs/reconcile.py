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
  (:mod:`sm_images.jobs.placeholders`);
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
  its backoff (:func:`sm_images.billing.ops.settle`), and an image that lost
  a committed swap is reconciled (:func:`sm_images.billing.repair.repair`);
* every live collection's stats are recomputed (the only way a box shrinks
  after deletes; there is no durable "touched" marker yet, so all of them,
  in batches);
* maps that are due and not claimed - a lost ``images.build_map``, a claim
  that expired, a withdrawn map - are requested again
  (:func:`sm_images.map.recover.reconcile_maps`).

Each of these is a phase of its own (:func:`sm_images.jobs.phases.run_phases`): one
that raises is logged and counted as ``failed_phases``, and the rest still run -
except the image dispatch, which runs only once ``repair_unleased`` succeeded
in the same pass (a legacy RUNNING row without a lease is still running).
The image dispatches - each on its own - are :mod:`sm_images.jobs.reconcile_dispatch`.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from functools import partial

from simple_module_db import all_tenants, finalize_session, tenant_context
from sqlalchemy import or_, select, update

from sm_images.ai.group_request import recover_group_runs
from sm_images.billing import ops as billing_ops
from sm_images.billing import repair as billing_repair
from sm_images.imports.recover import recover_imports
from sm_images.jobs.phases import run_phases
from sm_images.jobs.reconcile_dispatch import dispatch_images, ids, repair_unleased
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
from sm_images.pipeline.runtime import Runtime
from sm_images.regroup import control as regroup_control
from sm_images.regroup import jobs as regroup_jobs
from sm_images.services import stats
from sm_images.tenancy import all_tenants as tagged
from sm_images.tenancy import valid_tenant

__all__ = ["CUTOFF", "reconcile_async", "reconcile_tenant", "tenants"]

logger = logging.getLogger(__name__)

CUTOFF = timedelta(minutes=5)
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


async def _imports(runtime: Runtime, tenant: str, cutoff: datetime) -> dict[str, int]:
    jobs, items = await recover_imports(runtime, tenant, cutoff)
    return {"import_jobs": jobs, "import_items": items}


async def _recompute_stats(runtime: Runtime, tenant: str) -> int:
    found = await ids(
        runtime, select(Collection.id).where(Collection.tenant_id == tenant), Collection.id
    )
    for start in range(0, len(found), STATS_BATCH):
        async with runtime.session_factory() as db:
            for collection_id in found[start : start + STATS_BATCH]:
                await stats.recompute(db, collection_id)
            await finalize_session(db)
    return len(found)


async def reconcile_tenant(runtime: Runtime, tenant: str, now: datetime) -> Counter[str]:
    """One tenant's recovery; the caller has bound ``tenant``."""
    cutoff = now - CUTOFF
    factory = runtime.session_factory
    done: Counter[str] = Counter()
    # Looked up here, at call time, so each phase is the module's current one.
    phases = [
        ("repaired", partial(repair_unleased, runtime, tenant, cutoff)),
        # Only after a successful repair: an unleased RUNNING row is still running.
        ("dispatch", partial(dispatch_images, runtime, tenant, now, cutoff), "repaired"),
        ("restarts", partial(_restarts, runtime, tenant, now, cutoff)),
        ("regroups", partial(_regroups, runtime, tenant, cutoff)),
        ("import_jobs", partial(_imports, runtime, tenant, cutoff)),
        ("group_runs", partial(recover_group_runs, runtime, tenant, now, cutoff)),
        ("billing_ops", partial(billing_ops.settle, factory, tenant)),  # the database's clock
        ("billing_repaired", partial(billing_repair.repair, factory, tenant, now)),
        ("collections", partial(_recompute_stats, runtime, tenant)),
        ("maps", partial(reconcile_maps, runtime, tenant, now)),
    ]
    await run_phases(done, "reconcile", tenant, phases)
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
