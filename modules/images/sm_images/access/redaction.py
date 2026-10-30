"""Whether an image's original may still be the unredacted picture.

A display mutator (a blur, an anonymiser) writes the display copy everyone
else sees. Until it has *settled* for an image, its original - and every
rendition cut before it - may show what it exists to hide, so serving treats
the image as **pending**: no display, no renditions, the original protected.
Serving asks only when the image has no **trusted** display copy
(:func:`trusts_display`): one written by the collection's current display
mutator - installed, and the only enabled mutator or unknown step - is
redacted, and it and its current renditions are always served; one written by
another step (a crop), or by a step no longer installed, is no better than
the original.

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

A settled run only stands while the display copy it settled on does: when a
step publishes a new display copy, every *other* mutator's run - and every
uninstalled non-``prompt:`` step's, which might be one - goes back to
``pending`` (``pipeline.publish.invalidate_other_mutators``). So a blur that
completed before a crop re-read the original vouches for nothing once the
crop's copy is current; a disabled blur settles as a ``disabled`` placeholder,
which dispatch reopens - and re-runs - when it is enabled again.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import and_, exists, false, or_, select, true

from sm_images.models import Collection, Image, StepRun
from sm_images.models.enums import StepStatus
from sm_images.pipeline import registry
from sm_images.pipeline.config import validate_pipeline_config
from sm_images.pipeline.plan import BLOCKED_CODES

__all__ = ["gate_key", "pending", "ready_clause", "trusts_display"]


def _settles(status: StepStatus, code: str | None) -> bool:
    if status is StepStatus.COMPLETED:
        return True
    return status is StepStatus.SKIPPED and code not in BLOCKED_CODES


def _unknown(cfg: Any, sid: str) -> bool:
    """An enabled step that is not installed and might be a display mutator."""
    return cfg.steps[sid].state == "not_installed" and not sid.startswith(registry.PROMPT_PREFIX)


def trusts_display(collection: Collection, image: Image) -> bool:
    """Whether *image*'s display copy counts as redacted. All of:

    * the step that wrote it (``Image.display_step``) is enabled, installed
      and a display mutator - any version of it, so a re-run keeps serving;
    * no *other* enabled step is a display mutator;
    * no other enabled step is uninstalled: an unknown step might be one.

    ``prompt:*`` steps never write a display copy and are left out. A copy
    from any other step (a crop, before an anonymiser was enabled), from an
    uninstalled step, or from no recorded step is not trusted.
    """
    writer = image.display_step
    if image.display_key is None or writer is None:
        return False
    cfg = validate_pipeline_config(collection.pipeline_config, strict=False)
    enabled = [sid for sid in cfg.enabled() if not sid.startswith(registry.PROMPT_PREFIX)]
    if writer not in enabled:
        return False
    for sid in enabled:
        impl = registry.get_step(sid)
        if impl is None or bool(impl.mutates_display) != (sid == writer):
            return False
    return True


async def pending(db: Any, collection: Collection, image: Image) -> bool:
    mutators = _mutators(collection)
    if mutators is None:
        return True
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


def _mutators(collection: Collection) -> dict[str, Any] | None:
    """The enabled, installed display mutators; ``None`` when an enabled step
    is not installed (it might be one: everything is pending)."""
    cfg = validate_pipeline_config(collection.pipeline_config, strict=False)
    enabled = cfg.enabled()
    if any(_unknown(cfg, sid) for sid in enabled):
        return None
    return {
        sid: impl
        for sid in enabled
        if (impl := registry.get_step(sid)) is not None and impl.mutates_display
    }


def gate_key(collection: Collection) -> str:
    """The identity of *collection*'s redaction gate: everything
    :func:`ready_clause` decides in Python - ``protect_originals`` and the
    enabled, installed mutators at their installed versions, or "an enabled
    step is unknown". Two equal keys place the same images. A map archive is
    stamped with the key it was built under (``Collection.map_policy_rev``) and
    is not served under another: a pipeline save, a plugin installed or
    removed, a mutator's version bump."""
    mutators = _mutators(collection)
    if mutators is None:
        gate = "unknown"
    else:
        gate = ",".join(f"{sid}@{impl.version}" for sid, impl in sorted(mutators.items()))
    raw = f"{int(bool(collection.protect_originals))}|{gate}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def ready_clause(collection: Collection) -> Any:
    """SQL twin of ``trusts_display(...) or not pending(...)`` over the images of
    *collection*: the ones whose picture may be shown, and so the only ones the
    map may place (``sm_images.map``). Decided per collection in Python, then
    per image in SQL; ``tests/test_map_points.py`` checks it against the gate."""
    mutators = _mutators(collection)
    if mutators is None:
        return false()
    if not mutators:
        return false() if collection.protect_originals else true()
    settled = and_(
        *[
            exists(
                select(StepRun.id).where(
                    StepRun.image_id == Image.id,
                    StepRun.step == sid,
                    StepRun.step_version == impl.version,
                    or_(
                        StepRun.status == StepStatus.COMPLETED,
                        and_(
                            StepRun.status == StepStatus.SKIPPED,
                            or_(
                                StepRun.error_code.is_(None),
                                StepRun.error_code.not_in(sorted(BLOCKED_CODES)),
                            ),
                        ),
                    ),
                )
            )
            for sid, impl in mutators.items()
        ]
    )
    if len(mutators) != 1:  # two mutators: no display copy is trusted
        return settled
    (writer,) = mutators
    trusted = and_(Image.display_key.is_not(None), Image.display_step == writer)
    return or_(trusted, settled)
