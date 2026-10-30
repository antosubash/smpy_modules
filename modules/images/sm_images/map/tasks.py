"""``images.build_map(collection_id, generation)`` on the ``images`` queue.

Registered by the import in :mod:`sm_images.tasks`. The body runs through the
worker runtime in the message's tenant (:func:`~sm_images.pipeline.worker_runtime.run_task`);
a stale ``generation`` does nothing (:mod:`sm_images.map.build`). Not retried:
a failure cools the claim down, and ``images.reconcile`` asks again.
"""

from __future__ import annotations

import logging
import uuid

from celery import shared_task

from sm_images.jobs.task_config import BUILD_MAP

logger = logging.getLogger(__name__)

STUCK_AFTER_SECONDS = 2 * 3600
"""Above tippecanoe's one-hour ceiling plus the upload."""


@shared_task(name=BUILD_MAP, stuck_after=STUCK_AFTER_SECONDS)
def build_map(collection_id: str, generation: int) -> str:
    from sm_images.map.build import build_map_async
    from sm_images.pipeline.worker_runtime import run_task

    outcome = run_task(
        lambda runtime, tenant: build_map_async(
            runtime, tenant, uuid.UUID(collection_id), int(generation)
        )
    )
    logger.info("images.build_map collection=%s outcome=%s", collection_id, outcome)
    return outcome
