"""When a collection's map is rebuilt, and how a build is handed off.

**Counting.** Every map-relevant change bumps ``Collection.map_changes`` in the
transaction that makes it (:func:`changed`): a located image's processing
cycle concluding (``ImageProcessed`` - new points, a blur settling), a move, a
removal, a group change. A move or a removal also sets ``map_urgent_mark``:
those must not wait for the threshold. The current map remembers the count its
snapshot saw (``map_built_changes``).

**The threshold** (spec §5): rebuild once the changes since the snapshot reach
``map_rebuild_threshold_abs`` or ``map_rebuild_threshold_pct`` percent of the
points the map holds, whichever comes first (:func:`due`). A map of zero points
rebuilds on the first change.

**Requests coalesce.** :func:`request` bumps ``map_generation`` and claims the
collection (``map_claimed_until``) unless a build is already queued or running;
the build extends the claim while it works and clears it when it publishes.
A lost message or a dead worker leaves a claim that expires, and
``images.reconcile`` (:func:`reconcile_maps`) requests what is still due.

**A visibility change withdraws the map** (:func:`withdraw`, the portal's
revocation lesson) in the visibility change's own transaction: ``map_key`` is
cleared, so nothing is served until a fresh build publishes, and the generation
moves on, so a build that started before the change can never publish.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, Final

from simple_module_db import finalize_session, tenant_context
from simple_module_db.callbacks import register_on_commit
from sqlalchemy import or_, select, update

from sm_images.models import Collection, Image
from sm_images.pipeline.runtime import Runtime, current_runtime

__all__ = [
    "FAILED_COOLDOWN",
    "QUEUED_TTL",
    "changed",
    "due",
    "reconcile_maps",
    "request",
    "request_if_due",
    "withdraw",
]

logger = logging.getLogger(__name__)

QUEUED_TTL: Final = timedelta(minutes=10)
"""How long a request's claim holds before the build itself extends it."""
FAILED_COOLDOWN: Final = timedelta(minutes=15)
"""A failed or impossible build (no tippecanoe) is not retried before this."""
_SYNC: Final = {"synchronize_session": False}
_STATE: Final = (
    Collection.map_changes,
    Collection.map_built_changes,
    Collection.map_urgent_mark,
    Collection.map_image_count,
)


def now() -> datetime:
    return datetime.now(UTC)


def due(pending: int, baseline: int, *, urgent: bool, pct: int, abs_: int) -> bool:
    """Whether ``pending`` changes since the snapshot warrant a rebuild."""
    if pending <= 0:
        return False
    return urgent or pending >= abs_ or pending * 100 >= pct * baseline


def _due_row(row: Any, settings: Any) -> bool:
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

    from sm_images.map.tasks import build_map
    from sm_images.task_config import QUEUE_DEFAULT

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
    stmt = stmt.returning(Collection.map_generation).execution_options(**_SYNC)
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
) -> None:
    """Count ``count`` map changes in the caller's transaction, and request a
    build if that makes the map due. With ``image_id``, only if that image has a
    location (an unlocated image is not on the map)."""
    if count <= 0:
        return
    values: dict[str, Any] = {"map_changes": Collection.map_changes + count}
    if urgent:
        values["map_urgent_mark"] = Collection.map_changes + count
    stmt = update(Collection).where(Collection.id == collection_id)
    if image_id is not None:
        placed = select(Image.id).where(Image.id == image_id, Image.lat.is_not(None))
        stmt = stmt.where(placed.exists())
    stmt = stmt.values(**values).returning(*_STATE).execution_options(**_SYNC)
    row = (await db.execute(stmt)).first()
    runtime = runtime or current_runtime()
    if row is None or runtime is None or not _due_row(row, runtime.settings()):
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
    row = (await db.execute(select(*_STATE).where(Collection.id == collection_id))).first()
    if row is None or not _due_row(row, runtime.settings()):
        return None
    return await request(db, runtime, tenant, collection_id)


async def withdraw(
    db: Any, collection_id: uuid.UUID, *, runtime: Runtime | None, tenant: str
) -> None:
    """Stop serving the map now and build a fresh one: in the caller's
    transaction (a visibility change). The withdrawn archive is deleted after
    the commit; its intent lets the janitor finish if that delete fails."""
    from sm_images.map.build import drop_objects
    from sm_images.pipeline.publish import add_intents

    lock = select(Collection.map_key).where(Collection.id == collection_id)
    old = (await db.execute(lock.with_for_update(key_share=True))).scalar_one_or_none()
    await db.execute(
        update(Collection)
        .where(Collection.id == collection_id)
        .values(
            map_key=None,
            map_built_at=None,
            map_image_count=0,
            map_changes=Collection.map_changes + 1,
            map_urgent_mark=Collection.map_changes + 1,
        )
        .execution_options(**_SYNC)
    )
    if old:
        await add_intents(db, [old])
        if runtime is not None:
            register_on_commit(db, partial(drop_objects, runtime, [old]))
    await request(db, runtime, tenant, collection_id, force=True)


async def reconcile_maps(runtime: Runtime, tenant: str, at: datetime) -> int:
    """Request every unclaimed map of ``tenant`` that is due (the caller has
    bound it). Skipped while tippecanoe cannot be found: nothing could build."""
    from sm_images.map import pmtiles_build

    settings = runtime.settings()
    if pmtiles_build.locate(settings.tippecanoe_path) is None:
        return 0
    claimed = Collection.map_claimed_until
    stmt = select(Collection.id, *_STATE).where(
        Collection.tenant_id == tenant, or_(claimed.is_(None), claimed < at)
    )
    async with runtime.session_factory() as db:
        rows = list((await db.execute(stmt)).all())
        await finalize_session(db)
    requested = 0
    for collection_id, *state in rows:
        if not _due_row(state, settings):
            continue
        async with runtime.session_factory() as db:
            if await request(db, runtime, tenant, collection_id, at=at) is not None:
                requested += 1
            await finalize_session(db)
    return requested
