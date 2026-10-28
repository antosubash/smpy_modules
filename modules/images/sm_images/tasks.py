"""Celery tasks for images (autodiscovered by ``background_tasks``).

Imported by every process that builds the Celery app - the web process and
every worker, including the test runner's eager app - so it stays light:
Celery here, everything else inside the bodies. Routing and beat are in
:mod:`sm_images.task_config`.

* ``images.run_step(image_id, step, token)`` - execute one claimed run; its
  completion claims and enqueues whatever became ready.
* ``images.restart_collection(collection_id, scope, restart_id=None)`` - reset
  and re-dispatch a collection in chunks (``images_imports``), recorded so a
  lost one is resumed (``restart_id``) by reconcile.
* ``images.reconcile()`` - the five-minute recovery beat, also sent once when a
  worker comes up (``worker_ready``).

Bodies run through :mod:`sm_images.pipeline.worker_runtime`: no app, the
message's tenant (restored by ``background_tasks``' ``task_prerun``), a fresh
event loop per task.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from celery import shared_task
from celery.signals import worker_process_init, worker_ready

from sm_images.task_config import QUEUE_DEFAULT, RECONCILE, RESTART_COLLECTION, RUN_STEP

logger = logging.getLogger(__name__)

STUCK_AFTER_SECONDS = 2 * 3600


@shared_task(name=RUN_STEP, stuck_after=STUCK_AFTER_SECONDS)
def run_step(image_id: str, step: str, token: str) -> bool:
    from sm_images.pipeline.executor import run_step_async
    from sm_images.pipeline.worker_runtime import run_task

    return run_task(
        lambda runtime, tenant: run_step_async(
            runtime, tenant, uuid.UUID(image_id), step, uuid.UUID(token)
        )
    )


@shared_task(name=RESTART_COLLECTION, stuck_after=STUCK_AFTER_SECONDS)
def restart_collection(collection_id: str, scope: str, restart_id: str | None = None) -> int:
    from sm_images.pipeline.restart import restart_collection_async
    from sm_images.pipeline.worker_runtime import run_task

    if scope not in ("retry", "force", "stale"):
        raise ValueError(f"unknown restart scope {scope!r}")
    return run_task(
        lambda runtime, tenant: restart_collection_async(
            runtime,
            tenant,
            uuid.UUID(collection_id),
            scope,
            restart_id=uuid.UUID(restart_id) if restart_id else None,
        )
    )


@shared_task(name=RECONCILE)
def reconcile() -> dict[str, int]:
    from sm_images.pipeline.worker_runtime import run_platform
    from sm_images.reconcile import reconcile_async

    summary = run_platform(lambda runtime: reconcile_async(runtime, datetime.now(UTC)))
    if any(summary.values()):
        logger.info("images.reconcile %s", summary)
    return summary


@worker_ready.connect(weak=False, dispatch_uid="sm_images.reconcile_on_ready")
def reconcile_on_ready(sender: Any = None, **_: Any) -> None:
    """One recovery pass as the worker comes up. Only a send - no DB work and no
    event loop in the worker's main process - and no tenant on the message:
    the body enumerates tenants itself. A broker failure is logged; the beat
    entry runs it within five minutes anyway."""
    try:
        sender.app.send_task(RECONCILE, queue=QUEUE_DEFAULT)
    except Exception:
        logger.warning("images.reconcile_on_ready.send_failed", exc_info=True)


@worker_process_init.connect(weak=False, dispatch_uid="sm_images.forget_parent_runtime")
def forget_parent_runtime(**_: Any) -> None:
    """A prefork child must not reuse its parent's engine or storage clients."""
    from sm_images.pipeline.worker_runtime import reset_worker_runtime

    reset_worker_runtime()
