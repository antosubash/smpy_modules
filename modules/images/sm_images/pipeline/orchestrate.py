"""dispatch → run_step → complete → dispatch, in either delivery mode.

**Broker mode.** :func:`dispatch_ready` claims an image's ready steps and
enqueues ``images.run_step`` for each once the claim commits
(``enqueue_after_commit``, on the step's queue, stamped with the tenant). The
task body works, completes - which plans the next steps in the same
transaction - and enqueues those. Delivery is at-most-once per hand-off; a lost
message leaves a ``running`` row whose lease expires, and ``images.reconcile``
claims it again.

**Eager mode** (tests, a dev host without a broker). Nothing goes through
Celery: its eager mode runs a task body *inside the publish*, on the request's
event loop, where the body's ``asyncio.run`` cannot run. Instead every
hand-off becomes an item on one **iterative drain** owned by whoever started
it (:func:`submit`): a nested hand-off - a completion scheduling its dependants
- appends to the active drain and returns, so the chain runs to the end on the
calling loop, one item at a time, with no recursion, no ``create_task`` and no
helper thread. Items carry the tenant they were created under; Celery's
signals, which restore it for a real task, are bypassed.

Both modes run the same claim, work and completion code.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from collections.abc import Iterable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from simple_module_db import finalize_session, tenant_context

from sm_images.core.clock import utcnow
from sm_images.pipeline import advance
from sm_images.pipeline.claim import load_runs, lock_image
from sm_images.pipeline.cycle import bump_cycle, reset_runs
from sm_images.pipeline.eager_drain import drain_durable
from sm_images.pipeline.plan import FINAL, is_blocked, is_stale
from sm_images.pipeline.runtime import Runtime

__all__ = [
    "Dispatch",
    "RunStep",
    "Scope",
    "dispatch_ready",
    "rerun_image",
    "reset_image",
    "submit",
    "submit_dispatch",
]

logger = logging.getLogger(__name__)

Scope = Literal["retry", "force", "stale"]


@dataclass(frozen=True)
class Dispatch:
    tenant: str
    image_id: uuid.UUID


@dataclass(frozen=True)
class RunStep:
    tenant: str
    image_id: uuid.UUID
    step: str
    token: uuid.UUID


_drain: ContextVar[Any] = ContextVar("sm_images_drain", default=None)


async def _execute(runtime: Runtime, item: Any) -> None:
    if isinstance(item, Dispatch):
        await dispatch_ready(runtime, item.tenant, item.image_id)
        return
    from sm_images.pipeline.executor import run_step_async

    await run_step_async(runtime, item.tenant, item.image_id, item.step, item.token)


async def submit(runtime: Runtime, items: Iterable[Any]) -> None:
    """Run ``items`` on this loop (eager mode), appending to an active drain.

    Every item runs even if an earlier one fails; the first failure is raised
    once the queue is empty, so a test sees it and a request logs it.
    """
    active = _drain.get()
    if active is not None and not active.closed:
        active.extend(items)
        return
    queue = _Queue(items)
    reset = _drain.set(queue)
    first: BaseException | None = None
    wait = True
    try:
        while True:
            while queue:
                item = queue.popleft()
                try:
                    with tenant_context(item.tenant):
                        await _execute(runtime, item)
                except Exception as exc:
                    logger.exception("images.pipeline.eager_item_failed item=%r", item)
                    first = first or exc
            # Deliveries started by this work copied this context, so the
            # reruns their handlers submit land in ``queue``: keep it open
            # while waiting for them, then run whatever they added. Only the
            # wait is bounded: after a timeout (or with nothing to wait for)
            # it stops, but queued image work still runs before closing.
            if wait:
                wait = await drain_durable(runtime)
            if not queue:  # no await between this check and closing it
                break
    finally:
        queue.closed = True  # a later submit from a copied context starts afresh
        _drain.reset(reset)
    if first is not None:
        raise first


class _Queue(deque):
    closed = False


async def submit_dispatch(runtime: Runtime, tenant: str, image_id: uuid.UUID) -> None:
    """Plan ``image_id`` now: the drain in eager mode, a claim + enqueue otherwise."""
    if runtime.is_eager():
        await submit(runtime, [Dispatch(tenant, image_id)])
        return
    with tenant_context(tenant):
        await dispatch_ready(runtime, tenant, image_id)


async def dispatch_ready(runtime: Runtime, tenant: str, image_id: uuid.UUID) -> list[Any]:
    """Settle, claim and hand off ``image_id``'s ready steps; conclude its cycle."""
    lease_s = runtime.settings().step_lease_seconds
    async with runtime.session_factory() as db:
        found = await advance.plan_and_claim(db, tenant, image_id, None, lease_s)
        if found is not None:
            await advance.conclude(db, runtime, tenant, image_id, found)
        await finalize_session(db)
    return [] if found is None else found.claims


def _selected(scope: Scope, cfg: Any, runs: dict[str, Any], now: datetime) -> list[str]:
    enabled = set(cfg.enabled())
    out = []
    for sid, r in runs.items():
        if sid not in enabled:
            continue
        v = advance.view(r, now)
        abandoned = v.status.value == "running" and not v.lease_live
        # A plain pending run needs no reset (dispatch claims it), and resetting
        # it would start a new cycle for nothing.
        if v.status.value == "pending":
            continue
        if scope == "force":
            pick = not v.lease_live
        elif scope == "retry":
            pick = v.status.value == "failed" or is_blocked(v) or abandoned
        else:  # stale
            pick = (v.status in FINAL and is_stale(v, cfg)) or is_blocked(v)
        if pick:
            out.append(sid)
    return out


async def reset_image(db: Any, tenant: str, image_id: uuid.UUID, scope: Scope) -> list[str]:
    """Reset the runs ``scope`` selects (never a live lease) and, if any were,
    start a new processing cycle. Commit with the caller's session."""
    locked = await lock_image(db, tenant, image_id)
    if locked is None:
        return []
    now = utcnow()
    cfg = await advance.collection_config(db, tenant, locked.collection_id)
    runs = await load_runs(db, tenant, image_id)
    done = await reset_runs(db, tenant, image_id, _selected(scope, cfg, runs, now), now)
    # A step enabled after the image was planned has no run yet: stale (and part
    # of "all"); the dispatch that follows inserts it. Only a runnable one - the
    # overview counts no other as stale, and an uninstalled step would start a
    # new cycle on every re-run for nothing.
    missing = [s for s in cfg.runnable() if s not in runs] if runs and scope != "retry" else []
    if done or missing:
        await bump_cycle(db, tenant, image_id)
    return sorted([*done, *missing])


async def rerun_image(
    runtime: Runtime, tenant: str, image_id: uuid.UUID, scope: Scope
) -> list[str]:
    """Retry (failed and pending), force (everything) or re-run stale results."""
    with tenant_context(tenant):
        async with runtime.session_factory() as db:
            steps = await reset_image(db, tenant, image_id, scope)
            await finalize_session(db)
    await submit_dispatch(runtime, tenant, image_id)
    return steps
