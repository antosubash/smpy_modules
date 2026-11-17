"""Celery tasks for events (autodiscovered by ``background_tasks``).

Imported by every process that builds the Celery app, so it stays light: Celery
here, everything else inside the bodies. Routing, queues and beat are in
:mod:`sm_events.task_config`.

* ``events.publish_due()`` - the beat every minute: publishes every event whose
  ``publish_at`` has come (:mod:`sm_events.content.publish_due`).

Bodies run through :mod:`sm_events.core.worker`: no app, a fresh event loop per
task, and the body binds every tenant itself.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from celery.signals import worker_process_init

from sm_events.task_config import PUBLISH_DUE

logger = logging.getLogger(__name__)


@shared_task(name=PUBLISH_DUE)
def publish_due() -> dict[str, int]:
    """One pass of scheduled publishing; returns (and logs) its summary."""
    from sm_events.content.publish_due import publish_due_async
    from sm_events.core.clock import utcnow
    from sm_events.core.worker import run_platform

    summary = run_platform(lambda factory: publish_due_async(factory, now=utcnow()))
    logger.info(
        "events.publish_due: %d tenant(s), %d published, %d failed",
        summary["tenants"],
        summary["published"],
        summary["failed"],
    )
    return summary


@worker_process_init.connect(weak=False, dispatch_uid="sm_events.forget_parent_runtime")
def forget_parent_runtime(**_: Any) -> None:
    """A prefork child must not reuse its parent's engine."""
    from sm_events.core.worker import reset_worker_runtime

    reset_worker_runtime()
