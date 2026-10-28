"""Whether an image's original may still be the unredacted picture.

A display mutator (a blur, an anonymiser) writes the display copy everyone
else sees. Until it has *settled* for an image, its original - and every
rendition cut before it - may show what it exists to hide, so serving treats
the image as **pending**: no display, no renditions, the original protected.

Decided from persisted state, never from the live registry alone:

* ``Collection.protect_originals`` stays set after the mutator's plugin is
  uninstalled, and with it set and no installed mutator to ask, the answer is
  pending (fail closed);
* an enabled step that is not installed (other than ``prompt:*``, which never
  writes a display copy) might be the mutator: pending.

A mutator has settled when its run for this image is ``completed``, or a skip
the step itself returned ("nothing to redact"), **at the installed step
version**. A skip the planner decided (``plan.BLOCKED_CODES``:
``dependency_*``, ``not_installed``, ``disabled``) settles nothing.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from sm_images.models import Collection, Image, StepRun
from sm_images.models.enums import StepStatus
from sm_images.pipeline import registry
from sm_images.pipeline.config import validate_pipeline_config
from sm_images.pipeline.plan import BLOCKED_CODES

__all__ = ["pending"]


def _settles(status: StepStatus, code: str | None) -> bool:
    if status is StepStatus.COMPLETED:
        return True
    return status is StepStatus.SKIPPED and code not in BLOCKED_CODES


async def pending(db: Any, collection: Collection, image: Image) -> bool:
    cfg = validate_pipeline_config(collection.pipeline_config, strict=False)
    enabled = cfg.enabled()
    if any(
        cfg.steps[sid].state == "not_installed" and not sid.startswith(registry.PROMPT_PREFIX)
        for sid in enabled
    ):
        return True
    mutators = {
        sid: impl
        for sid in enabled
        if (impl := registry.get_step(sid)) is not None and impl.mutates_display
    }
    if not mutators:
        return bool(collection.protect_originals)
    stmt = select(StepRun.step, StepRun.status, StepRun.error_code, StepRun.step_version).where(
        StepRun.image_id == image.id, StepRun.step.in_(list(mutators))
    )
    settled = {
        step
        for step, status, code, version in (await db.execute(stmt)).all()
        if version == mutators[step].version and _settles(StepStatus(status), code)
    }
    return any(sid not in settled for sid in mutators)
