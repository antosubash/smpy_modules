"""The processing pipeline's entry points, as ingest sees them.

**Placeholder until Tasks 9-11.** Two things live here so ingest has a stable
call site:

* :func:`enabled_steps` - which steps a collection runs, read straight off
  ``Collection.pipeline_config``. The shape (Task 11 formalises it, with the
  step registry validating ids and params)::

      {"steps": {"exif": {}, "renditions": {"enabled": true}, "quality": {"enabled": false, ...}}}

  A step is enabled when it appears under ``"steps"`` with an object value
  whose ``"enabled"`` is not ``false``. Everything else in the object is the
  step's params. Order is the mapping's order; the executor orders by
  ``requires`` anyway.
* :func:`dispatch` - hand an image to the workers once its row is durable.
  Ingest calls it inside the transaction; the send runs only after that
  transaction commits (``register_on_commit``), and never on a rollback. Task 10
  replaces :func:`_send` with the real enqueue.
"""

from __future__ import annotations

import uuid
from functools import partial
from typing import Any

from simple_module_db.callbacks import register_on_commit

__all__ = ["dispatch", "enabled_steps"]


def enabled_steps(config: dict[str, Any] | None) -> list[str]:
    steps = (config or {}).get("steps")
    if not isinstance(steps, dict):
        return []
    return [
        step
        for step, params in steps.items()
        if isinstance(step, str) and isinstance(params, dict) and params.get("enabled") is not False
    ]


async def _send(image_id: uuid.UUID) -> None:
    """No-op until Task 10 enqueues the image's pending steps."""
    return


def dispatch(db: Any, image_id: uuid.UUID) -> None:
    """Queue ``image_id`` for the workers once ``db`` commits."""
    register_on_commit(db, partial(_dispatch_after_commit, image_id))


async def _dispatch_after_commit(image_id: uuid.UUID) -> None:
    # Looked up at call time so Task 10 (or a test) can replace ``_send``.
    await _send(image_id)
