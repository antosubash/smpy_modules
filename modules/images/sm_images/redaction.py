"""Whether an image's original may still be the unredacted picture.

A display mutator (a blur, an anonymiser) writes the display copy everyone
else sees. Until it has *settled* for an image, its original - and every
rendition cut before it - may show what it exists to hide, so serving treats
the image as **pending**: no display, no renditions, the original protected.
Serving asks only when the image has no **trusted** display copy
(:func:`trusts_display`): one written by the collection's current display
mutator is redacted, and it and its current renditions are always served; one
written by another step (a crop) is no better than the original.

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

__all__ = ["pending", "trusts_display"]


def _settles(status: StepStatus, code: str | None) -> bool:
    if status is StepStatus.COMPLETED:
        return True
    return status is StepStatus.SKIPPED and code not in BLOCKED_CODES


def _unknown(cfg: Any, sid: str) -> bool:
    """An enabled step that is not installed and might be a display mutator."""
    return cfg.steps[sid].state == "not_installed" and not sid.startswith(registry.PROMPT_PREFIX)


def trusts_display(collection: Collection, image: Image) -> bool:
    """Whether *image*'s display copy counts as redacted: it exists, and the
    step that wrote it (``Image.display_step``) is the collection's enabled
    display mutator - any version of it, so a re-run keeps serving the copy.
    An enabled step that is not installed is taken at its word: it wrote a
    display copy once, so it was a mutator, and uninstalling it does not make
    its copy unredacted. A copy from any other step (a crop, say, before an
    anonymiser was enabled), or from no recorded step, is not trusted.
    """
    if image.display_key is None or image.display_step is None:
        return False
    cfg = validate_pipeline_config(collection.pipeline_config, strict=False)
    if image.display_step not in cfg.enabled():
        return False
    impl = registry.get_step(image.display_step)
    return bool(impl.mutates_display) if impl is not None else _unknown(cfg, image.display_step)


async def pending(db: Any, collection: Collection, image: Image) -> bool:
    cfg = validate_pipeline_config(collection.pipeline_config, strict=False)
    enabled = cfg.enabled()
    if any(_unknown(cfg, sid) for sid in enabled):
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
