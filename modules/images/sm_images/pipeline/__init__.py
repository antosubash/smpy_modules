"""The processing pipeline's entry points, as ingest sees them.

* :func:`enabled_steps` - which steps a collection runs, read straight off
  ``Collection.pipeline_config``::

      {"steps": {"exif": {}, "renditions": {"enabled": true}, "quality": {"enabled": false, ...}}}

  A step is enabled when it appears under ``"steps"`` with an object value
  whose ``"enabled"`` is not ``false``. Everything else in the object is the
  step's params (validated by :func:`.config.validate_pipeline_config`).
  Ingest creates a pending ``StepRun`` for each, ids with no installed
  implementation included: the executor settles those as skipped.
* :func:`dispatch` - hand an image to the pipeline once its row is durable.
  Ingest calls it inside the transaction; :func:`_send` runs only after that
  transaction commits (``register_on_commit``), never on a rollback, in the
  tenant bound when it was queued. It plans the image in a fresh session -
  claims and hands off its ready steps (:mod:`.orchestrate`) - through the web
  process's runtime, which images' ``on_startup`` sets. With no runtime (a
  process that never started the module) nothing is sent; the pending rows
  wait for ``images.reconcile``.
"""

from __future__ import annotations

import logging
import uuid
from functools import partial
from typing import Any

from simple_module_db.callbacks import register_on_commit
from simple_module_db.listeners import current_tenant_id

__all__ = ["dispatch", "enabled_steps", "queue_auto_run"]

logger = logging.getLogger(__name__)


def enabled_steps(config: dict[str, Any] | None) -> list[str]:
    steps = (config or {}).get("steps")
    if not isinstance(steps, dict):
        return []
    return [
        step
        for step, params in steps.items()
        if isinstance(step, str) and isinstance(params, dict) and params.get("enabled") is not False
    ]


async def _send(image_id: uuid.UUID, tenant: str) -> None:
    from sm_images.pipeline.orchestrate import submit_dispatch
    from sm_images.pipeline.runtime import current_runtime

    runtime = current_runtime()
    if runtime is None:
        logger.warning("images.pipeline.no_runtime image=%s: left for reconcile", image_id)
        return
    await submit_dispatch(runtime, tenant, image_id)


def dispatch(db: Any, image_id: uuid.UUID) -> None:
    """Queue ``image_id`` for the pipeline once ``db`` commits."""
    tenant = current_tenant_id.get()
    if tenant is None:
        from sm_images.tenancy import TenantUnbound

        raise TenantUnbound("pipeline.dispatch needs a bound tenant")
    register_on_commit(db, partial(_dispatch_after_commit, image_id, tenant))


async def queue_auto_run(
    db: Any, collection: Any, image_id: uuid.UUID, *, enabled: bool = True
) -> None:
    """Request the collection's ``auto_run`` image prompts for ``image_id``.

    Pending ``prompt:<id>`` rows in ``db``'s transaction, which the image's
    :func:`dispatch` plans after the commit (behind the display mutator, like
    every AI step). Called by the one ingest entry point next to
    :func:`dispatch`, so every path - multipart, base64, direct upload,
    GeoJSON (URL and base64) and ZIP - reaches it; an import passes its job's
    ``auto_run_prompts`` as ``enabled``. A no-op without the ``[ai]`` extra.
    """
    if not enabled:
        return
    from sm_images.ai import prompt_steps

    await prompt_steps.request_auto_run(db, collection, image_id)


async def _dispatch_after_commit(image_id: uuid.UUID, tenant: str) -> None:
    # Looked up at call time so a test can replace ``_send``.
    await _send(image_id, tenant)
