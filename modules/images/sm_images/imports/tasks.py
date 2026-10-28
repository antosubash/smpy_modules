"""The import Celery tasks, registered by importing this module from
:mod:`sm_images.tasks` (what ``background_tasks`` autodiscovers).

Light like :mod:`sm_images.tasks`: Celery here, everything else inside the
bodies, which run through :func:`~sm_images.pipeline.worker_runtime.run_task`
(the message's tenant, a fresh loop, the worker runtime bound for ingest's
after-commit dispatch).

* ``images.import_geojson(job_id, generation)`` - stage, stream and record a
  GeoJSON source; a stale ``generation`` does nothing.
* ``images.download_items(job_id, ids, generation)`` - fetch and settle a
  batch of URL items for a runner of ``generation``.
* ``images.reset_import(job_id, generation)`` - the ``resetting`` phase of a
  restart or retry-failed, then the runner.
"""

from __future__ import annotations

import uuid

from celery import shared_task

from sm_images.task_config import DOWNLOAD_ITEMS, IMPORT_GEOJSON, RESET_IMPORT

__all__ = ["download_items", "import_geojson", "reset_import"]

STUCK_AFTER_SECONDS = 12 * 3600


@shared_task(name=IMPORT_GEOJSON, stuck_after=STUCK_AFTER_SECONDS)
def import_geojson(job_id: str, generation: int) -> str:
    from sm_images.imports.runner import import_geojson_async
    from sm_images.pipeline.worker_runtime import run_task

    return run_task(
        lambda runtime, tenant: import_geojson_async(
            runtime, tenant, uuid.UUID(job_id), int(generation)
        )
    )


@shared_task(name=DOWNLOAD_ITEMS, stuck_after=3600)
def download_items(job_id: str, ids: list[int], generation: int) -> int:
    from sm_images.imports.download import download_items_async
    from sm_images.pipeline.worker_runtime import run_task

    return run_task(
        lambda runtime, tenant: download_items_async(
            runtime, tenant, uuid.UUID(job_id), int(generation), [int(i) for i in ids]
        )
    )


@shared_task(name=RESET_IMPORT, stuck_after=STUCK_AFTER_SECONDS)
def reset_import(job_id: str, generation: int) -> str:
    from sm_images.imports.reset import run_reset
    from sm_images.pipeline.worker_runtime import run_task

    return run_task(
        lambda runtime, tenant: run_reset(runtime, tenant, uuid.UUID(job_id), int(generation))
    )
