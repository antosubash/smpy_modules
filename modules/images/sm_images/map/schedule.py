"""When a collection's map is rebuilt, and how a build is handed off.

**Counting.** Every map-relevant change bumps ``Collection.map_changes`` in the
transaction that makes it (:func:`changed`): a located image's processing
cycle concluding (``ImageProcessed`` - new points, a blur settling), a move, a
removal, a group change. A first location also sets ``map_urgent_mark``; a
move or a removal goes further and withdraws the archive (``map.revoke``):
the old point must not stay served. The current map remembers the count its
snapshot saw (``map_built_changes``).

**The threshold** (spec §5): rebuild once the changes since the snapshot reach
``map_rebuild_threshold_abs`` or ``map_rebuild_threshold_pct`` percent of the
points the map holds, whichever comes first (:func:`due`). A map of zero points
rebuilds on the first change.

**Requests coalesce.** :func:`request` bumps ``map_generation`` and claims the
collection (``map_claimed_until``) unless a build is already queued or running;
the build extends the claim while it works and clears it when it publishes.
A lost message or a dead worker leaves a claim that expires, and
``images.reconcile`` (:func:`sm_images.map.recover.reconcile_maps`) requests
what is still due.

Points that must *leave* the map do not wait for any of this: a visibility
change, a removed point and a change of the redaction gate withdraw the
archive in their own transaction (:mod:`sm_images.map.revoke`).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, Final

from simple_module_db import tenant_context
from simple_module_db.callbacks import register_on_commit
from sqlalchemy import or_, select, update

from sm_images.clock import utcnow as now
from sm_images.constants import NO_SYNC
from sm_images.models import Collection, Image
from sm_images.pipeline.runtime import Runtime, current_runtime

__all__ = [
    "FAILED_COOLDOWN",
    "MAP_STATE",
    "QUEUED_TTL",
    "changed",
    "due",
    "due_row",
    "rebuild_pending",
    "request",
    "request_if_due",
]

logger = logging.getLogger(__name__)

QUEUED_TTL: Final = timedelta(minutes=10)
"""How long a request's claim holds before the build itself extends it."""
FAILED_COOLDOWN: Final = timedelta(minutes=15)
"""A failed or impossible build (no tippecanoe) is not retried before this."""
MAP_STATE: Final = (
    Collection.map_changes,
    Collection.map_built_changes,
    Collection.map_urgent_mark,
    Collection.map_image_count,
)


def due(pending: int, baseline: int, *, urgent: bool, pct: int, abs_: int) -> bool:
    """Whether ``pending`` changes since the snapshot warrant a rebuild."""
    if pending <= 0:
        return False
    return urgent or pending >= abs_ or pending * 100 >= pct * baseline


def rebuild_pending(collection: Collection, at: datetime | None = None) -> bool:
    """Whether the served archive predates changes a rebuild is on its way for:
    one is claimed (queued or running), or the changes are due (a request
    reconcile has not made yet). A viewer should read the points then."""
    if collection.map_changes <= collection.map_built_changes:
        return False
    claimed = collection.map_claimed_until
    if claimed is not None and claimed.replace(tzinfo=claimed.tzinfo or UTC) > (at or now()):
        return True
    runtime = current_runtime()
    if runtime is None:
        return False
    row = tuple(getattr(collection, c.key) for c in MAP_STATE)
    return due_row(row, runtime.settings())


def due_row(row: Any, settings: Any) -> bool:
    changes, built, urgent_mark, baseline = row
    return due(
        changes - built,
        baseline,
        urgent=urgent_mark > built,
        pct=settings.map_rebuild_threshold_pct,
        abs_=settings.map_rebuild_threshold_abs,
    )


async def _eager_build(runtime: Runtime, tenant: str, collection_id: uuid.UUID, gen: int) -> None:
    from sm_images.map import build

    try:
        with tenant_context(tenant):
            await build.build_map_async(runtime, tenant, collection_id, gen)
    except Exception:
        logger.exception("images.map.eager_build_failed collection=%s", collection_id)


def hand_off(db: Any, runtime: Runtime, tenant: str, collection_id: uuid.UUID, gen: int) -> None:
    """Build generation ``gen`` once ``db`` commits: inline when eager (a dev
    host without a broker), else ``images.build_map`` on the ``images`` queue."""
    if not runtime.maps:
        return
    if runtime.is_eager():
        register_on_commit(db, partial(_eager_build, runtime, tenant, collection_id, gen))
        return
    from background_tasks import enqueue_after_commit
    from background_tasks.tenant_context import TENANT_HEADER

    from sm_images.jobs.task_config import QUEUE_DEFAULT
    from sm_images.map.tasks import build_map

    sig = build_map.s().set(queue=QUEUE_DEFAULT, headers={TENANT_HEADER: tenant})
    enqueue_after_commit(db, sig, str(collection_id), gen)


async def request(
    db: Any,
    runtime: Runtime | None,
    tenant: str,
    collection_id: uuid.UUID,
    *,
    force: bool = False,
    at: datetime | None = None,
) -> int | None:
    """Claim a new generation and hand it off; ``None`` when a build is already
    claimed (unless ``force``). Without a runtime the generation still moves
    on, unclaimed, and reconcile requests it."""
    at = at or now()
    stmt = update(Collection).where(Collection.id == collection_id)
    if not force:
        claimed = Collection.map_claimed_until
        stmt = stmt.where(or_(claimed.is_(None), claimed < at))
    stmt = stmt.values(
        map_generation=Collection.map_generation + 1,
        map_claimed_until=at + QUEUED_TTL if runtime is not None else None,
    )
    stmt = stmt.returning(Collection.map_generation).execution_options(**NO_SYNC)
    gen = (await db.execute(stmt)).scalar_one_or_none()
    if gen is not None and runtime is not None:
        hand_off(db, runtime, tenant, collection_id, gen)
    return gen


async def changed(
    db: Any,
    collection_id: uuid.UUID,
    *,
    count: int = 1,
    urgent: bool = False,
    image_id: uuid.UUID | None = None,
    runtime: Runtime | None = None,
    tenant: str | None = None,
    request_build: bool = True,
) -> None:
    """Count ``count`` map changes in the caller's transaction, and request a
    build if that makes the map due (unless ``request_build`` is false: the
    next check - the cycle's ``ImageProcessed``, reconcile - finds it due). With
    ``image_id``, only if that image has a location (an unlocated image is not
    on the map)."""
    if count <= 0:
        return
    values: dict[str, Any] = {"map_changes": Collection.map_changes + count}
    if urgent:
        values["map_urgent_mark"] = Collection.map_changes + count
    stmt = update(Collection).where(Collection.id == collection_id)
    if image_id is not None:
        placed = select(Image.id).where(Image.id == image_id, Image.lat.is_not(None))
        stmt = stmt.where(placed.exists())
    stmt = stmt.values(**values).returning(*MAP_STATE).execution_options(**NO_SYNC)
    row = (await db.execute(stmt)).first()
    if not request_build:
        return
    runtime = runtime or current_runtime()
    if row is None or runtime is None or not due_row(row, runtime.settings()):
        return
    if tenant is None:
        from sm_images.tenancy import bound_tenant

        tenant = bound_tenant()
    await request(db, runtime, tenant, collection_id)


async def request_if_due(
    db: Any, runtime: Runtime, tenant: str, collection_id: uuid.UUID
) -> int | None:
    """Request a build if the collection's map is due (a build that just
    published re-checks: changes may have landed while it ran)."""
    row = (await db.execute(select(*MAP_STATE).where(Collection.id == collection_id))).first()
    if row is None or not due_row(row, runtime.settings()):
        return None
    return await request(db, runtime, tenant, collection_id)
