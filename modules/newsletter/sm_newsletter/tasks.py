"""Celery tasks for newsletter (autodiscovered by ``background_tasks``).

Imported by every process that builds the Celery app - the web process and
every worker, including the test runner's eager app - so it stays light:
Celery here, everything else inside the bodies. Routing, queues and beat are
in :mod:`sm_newsletter.task_config`.

* ``newsletter.reconcile_suppressions()`` - the hourly beat: every tenant's
  list opt-outs re-read from records into the suppression store
  (:mod:`sm_newsletter.core.suppression.reconcile`).

Bodies run through :mod:`sm_newsletter.core.worker`: no app, a fresh event
loop per task, and the reconcile binds each tenant itself.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from celery.signals import worker_process_init

from sm_newsletter.task_config import RECONCILE_SUPPRESSIONS

logger = logging.getLogger(__name__)


@shared_task(name=RECONCILE_SUPPRESSIONS)
def reconcile_suppressions() -> dict[str, int]:
    """One reconcile pass; returns (and logs) its summary."""
    from sm_newsletter.core.clock import utcnow
    from sm_newsletter.core.suppression.reconcile import reconcile_async
    from sm_newsletter.core.worker import run_platform

    now = utcnow()
    summary = run_platform(lambda factory: reconcile_async(factory, now=now))
    logger.info(
        "newsletter.reconcile_suppressions: %d list(s), %d new suppression(s), %d failed",
        summary["lists"],
        summary["suppressed"],
        summary["failed"],
    )
    return summary


@worker_process_init.connect(weak=False, dispatch_uid="sm_newsletter.forget_parent_runtime")
def forget_parent_runtime(**_: Any) -> None:
    """A prefork child must not reuse its parent's engine."""
    from sm_newsletter.core.worker import reset_worker_runtime

    reset_worker_runtime()
