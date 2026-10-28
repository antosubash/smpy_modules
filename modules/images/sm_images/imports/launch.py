"""Handing import work on: inline when eager, a Celery message otherwise.

Eager (tests, a dev host without a broker) runs the body on the calling event
loop - never ``.delay()``: Celery's eager mode would run the task body inside
the publish, on this loop, where its ``asyncio.run`` cannot start. A broker
process sends the message stamped with the tenant header, which the
framework's ``task_prerun`` turns back into the bound tenant.

* the runner goes to ``images_imports`` (concurrency 1: it is a long stream);
* downloads go to ``images`` in batches of :data:`DOWNLOAD_BATCH`, each
  carrying the moment it was sent, so a download that reconcile re-sent in the
  meantime is not fetched twice (``download._claim``).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Final

from sm_images.pipeline.runtime import Runtime

__all__ = ["DOWNLOAD_BATCH", "launch_downloads", "launch_runner"]

DOWNLOAD_BATCH: Final = 50


async def launch_runner(runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int) -> None:
    if runtime.is_eager():
        from sm_images.imports.runner import import_geojson_async

        await import_geojson_async(runtime, tenant, job_id, generation)
        return
    from background_tasks.tenant_context import TENANT_HEADER

    from sm_images.imports.tasks import import_geojson
    from sm_images.task_config import QUEUE_IMPORTS

    import_geojson.s(str(job_id), generation).apply_async(
        queue=QUEUE_IMPORTS, headers={TENANT_HEADER: tenant}
    )


async def launch_downloads(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, ids: Sequence[int]
) -> None:
    if not ids:
        return
    if runtime.is_eager():
        from sm_images.imports.download import download_items_async

        await download_items_async(runtime, tenant, job_id, list(ids))
        return
    from background_tasks.tenant_context import TENANT_HEADER

    from sm_images.imports.jobs import now
    from sm_images.imports.tasks import download_items
    from sm_images.task_config import QUEUE_DEFAULT

    sent = now().isoformat()
    for start in range(0, len(ids), DOWNLOAD_BATCH):
        batch = [int(i) for i in ids[start : start + DOWNLOAD_BATCH]]
        download_items.s(str(job_id), batch, sent).apply_async(
            queue=QUEUE_DEFAULT, headers={TENANT_HEADER: tenant}
        )
