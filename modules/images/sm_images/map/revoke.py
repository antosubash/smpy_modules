"""Taking points off the published map at once (the portal's revocation lesson).

The threshold (:mod:`~sm_images.map.schedule`) is for points *arriving*. A
point that must *leave* cannot wait for a rebuild, so these run in the
transaction that makes it leave and :func:`withdraw` the archive there:

* :func:`withdraw` - ``map_key`` is cleared (nothing is served until a fresh
  build publishes) and the generation moves on (a build that snapshotted
  before the change can never publish), then a fresh build is requested.
  Callers: a visibility change (``services.collections.set_visibility``), a
  located image trashed, its location cleared or moved (:func:`point_removed`;
  a move by a later EXIF read too, ``pipeline.publish``), a pipeline save that
  changes the redaction gate (:func:`gate_saved`).
* :func:`gate_reopened` - a located image whose display mutator's settled run
  goes back to ``pending`` leaves the map too (``redaction.ready_clause``), so
  it withdraws as well; the rebuild is deferred to the next check.

A change of the gate that no transaction makes - a mutator plugin installed,
removed or bumped - is caught when serving (an archive stamped with another
``redaction.gate_key`` is a 404) and withdrawn by ``images.reconcile``
(:mod:`~sm_images.map.recover`).
"""

from __future__ import annotations

import uuid
from functools import partial
from typing import Any

from simple_module_db.callbacks import register_on_commit
from sqlalchemy import select, update

from sm_images.access import redaction
from sm_images.constants import NO_SYNC
from sm_images.intents import add_intents
from sm_images.map.objects import drop_objects
from sm_images.map.schedule import request
from sm_images.models import Collection, Image, StepRun
from sm_images.models.enums import StepStatus
from sm_images.pipeline import registry
from sm_images.pipeline.runtime import Runtime, current_runtime

__all__ = ["gate_reopened", "gate_saved", "may_mutate", "point_removed", "withdraw"]


async def withdraw(
    db: Any, collection_id: uuid.UUID, *, runtime: Runtime | None, tenant: str
) -> None:
    """Stop serving the map now and build a fresh one, in the caller's
    transaction. The withdrawn archive is deleted after the commit; its intent
    lets the janitor finish if that delete fails (or there is no runtime)."""
    lock = select(Collection.map_key).where(Collection.id == collection_id)
    old = (await db.execute(lock.with_for_update(key_share=True))).scalar_one_or_none()
    await db.execute(
        update(Collection)
        .where(Collection.id == collection_id)
        .values(
            map_key=None,
            map_policy_rev=None,
            map_built_at=None,
            map_image_count=0,
            map_changes=Collection.map_changes + 1,
            map_urgent_mark=Collection.map_changes + 1,
        )
        .execution_options(**NO_SYNC)
    )
    if old:
        await add_intents(db, [old])
        if runtime is not None:
            register_on_commit(db, partial(drop_objects, runtime, [old]))
    await request(db, runtime, tenant, collection_id, force=True)


async def point_removed(db: Any, collection: Collection) -> None:
    """A located image was trashed, lost its location or moved: its point (at
    the old place) is off the map now."""
    await withdraw(db, collection.id, runtime=current_runtime(), tenant=collection.tenant_id)


async def gate_saved(db: Any, collection: Collection, before: str) -> None:
    """After a pipeline save (or a preset applied): ``before`` is the gate key
    the collection had. A different gate places other images, so the archive
    built under the old one goes, whichever way the gate moved."""
    if redaction.gate_key(collection) != before:
        await withdraw(db, collection.id, runtime=current_runtime(), tenant=collection.tenant_id)


def may_mutate(step: str) -> bool:
    """A registered display mutator, or an unknown step that might be one
    (``prompt:*`` never writes a display copy)."""
    impl = registry.get_step(step)
    if impl is None:
        return not step.startswith(registry.PROMPT_PREFIX)
    return bool(impl.mutates_display)


async def gate_reopened(db: Any, tenant: str, image_id: uuid.UUID, steps: list[str]) -> None:
    """Call *before* the runs of ``steps`` go back to ``pending``: if one of them
    is a (possible) display mutator that had settled and the image is located,
    the image may just have left the map: the archive is withdrawn and a build
    in flight fenced. Over-withdraws when the image keeps a trusted display
    copy: an extra rebuild, never a point served that should not be.

    These resets run deep in the pipeline, with no runtime to hand a build to,
    so the fresh generation stays unclaimed and ``images.reconcile`` requests
    it; the withdrawn archive's intent lets the janitor delete it."""
    mutators = [s for s in steps if may_mutate(s)]
    if not mutators:
        return
    settled = select(StepRun.id).where(
        StepRun.tenant_id == tenant,
        StepRun.image_id == Image.id,
        StepRun.step.in_(mutators),
        StepRun.status.in_([StepStatus.COMPLETED, StepStatus.SKIPPED]),
    )
    stmt = select(Image.collection_id).where(
        Image.id == image_id, Image.lat.is_not(None), settled.exists()
    )
    collection_id = (await db.execute(stmt)).scalar_one_or_none()
    if collection_id is not None:
        await withdraw(db, collection_id, runtime=None, tenant=tenant)
