"""Advance one image while holding its lock: settle, claim, conclude the cycle.

Shared by a plain dispatch (:func:`plan_and_claim`) and by a completion, which
runs the same planning inside its own transaction - so the decision that an
image is done, and ``ImageProcessed``, commit together with the last result
and no crash can fall between them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any

from simple_module_db.callbacks import register_on_commit
from sqlalchemy import select

from sm_images import events
from sm_images.contracts.events import ImageProcessed
from sm_images.models import Collection, StepRun
from sm_images.models.enums import StepStatus
from sm_images.pipeline import registry
from sm_images.pipeline.claim import (
    Claim,
    LockedImage,
    claim,
    insert_missing,
    load_runs,
    lock_image,
    settle,
)
from sm_images.pipeline.config import validate_pipeline_config
from sm_images.pipeline.cycle import mark_processed
from sm_images.pipeline.plan import RunView, plan
from sm_images.pipeline.runtime import Runtime

__all__ = ["Advanced", "advance_locked", "claim_ready", "conclude", "plan_and_claim", "view"]

DEFAULT_QUEUE = "images"


@dataclass(frozen=True)
class Advanced:
    locked: LockedImage
    claims: list[Claim]
    final: bool


def view(run: StepRun, now: datetime) -> RunView:
    live = (
        run.status is StepStatus.RUNNING
        and run.lease_expires_at is not None
        and run.lease_expires_at >= now
    )
    return RunView(run.step, run.status, run.step_version, run.error_code, live)


async def collection_config(db: Any, tenant: str, collection_id: uuid.UUID) -> Any:
    stmt = select(Collection.pipeline_config).where(
        Collection.id == collection_id, Collection.tenant_id == tenant
    )
    return validate_pipeline_config((await db.execute(stmt)).scalar_one_or_none(), strict=False)


async def advance_locked(
    db: Any, tenant: str, image_id: uuid.UUID, locked: LockedImage, now: datetime, lease_s: int
) -> Advanced:
    cfg = await collection_config(db, tenant, locked.collection_id)
    runs = await load_runs(db, tenant, image_id)
    decided = plan(cfg, {sid: view(r, now) for sid, r in runs.items()})
    await insert_missing(db, image_id, decided.missing)
    for s in decided.settle:
        await settle(db, tenant, image_id, s.step, s.status, s.code, now)
    claims = await claim(db, tenant, image_id, decided.ready, now, lease_s)
    return Advanced(locked, claims, decided.final and not claims)


async def plan_and_claim(
    db: Any, tenant: str, image_id: uuid.UUID, now: datetime, lease_s: int
) -> Advanced | None:
    locked = await lock_image(db, tenant, image_id)
    if locked is None:
        return None
    return await advance_locked(db, tenant, image_id, locked, now, lease_s)


async def claim_ready(db: Any, image_id: uuid.UUID, now: datetime, lease_s: int) -> list[Claim]:
    """Claim every ready step of ``image_id`` in the bound tenant (one ``UPDATE``)."""
    from sm_images.tenancy import bound_tenant

    found = await plan_and_claim(db, bound_tenant(), image_id, now, lease_s)
    return [] if found is None else found.claims


async def _processed(db: Any, runtime: Runtime, tenant: str, image_id: uuid.UUID) -> None:
    won = await mark_processed(db, tenant, image_id)
    bus = runtime.bus()
    if won is None or bus is None:
        return
    collection_id, cycle = won
    event = ImageProcessed(tenant, str(collection_id), str(image_id), cycle)
    if bus.durable.handler_names(ImageProcessed):
        await bus.publish_durable_or_inline(event, db)
    events.emit(db, bus, event)


def _schedule(
    db: Any, runtime: Runtime, tenant: str, image_id: uuid.UUID, claims: list[Claim]
) -> None:
    """Hand each claim to a worker once ``db`` commits (eager: to the drain)."""
    if runtime.is_eager():
        from sm_images.pipeline.orchestrate import RunStep, submit

        items = [RunStep(tenant, image_id, c.step, c.token) for c in claims]
        register_on_commit(db, partial(submit, runtime, items))
        return
    from background_tasks import enqueue_after_commit
    from background_tasks.tenant_context import TENANT_HEADER

    from sm_images.tasks import run_step

    for c in claims:
        impl = registry.get_step(c.step)
        queue = impl.queue if impl is not None else DEFAULT_QUEUE
        sig = run_step.s().set(queue=queue, headers={TENANT_HEADER: tenant})
        enqueue_after_commit(db, sig, str(image_id), c.step, str(c.token))


async def conclude(
    db: Any, runtime: Runtime, tenant: str, image_id: uuid.UUID, advanced: Advanced
) -> None:
    """Decide ``ImageProcessed`` if the cycle is done; schedule the claims."""
    if advanced.final:
        await _processed(db, runtime, tenant, image_id)
    if advanced.claims:
        _schedule(db, runtime, tenant, image_id, advanced.claims)
