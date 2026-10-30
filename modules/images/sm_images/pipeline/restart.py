"""Re-run a whole collection: ``images.restart_collection``'s body.

A restart is a durable record (:class:`PipelineRestart`), so one lost to a
dead worker or a lost message is finished by ``images.reconcile``. Images are
walked by keyset in chunks of at most 1000. Each image is reset in its own
short transaction that also advances the record's cursor *conditionally on
its previous value* - so an image is reset at most once per restart, even with
two runners on one record, and a runner that lost that race stops. Resuming
re-dispatches the cursor's image first: its reset committed, its dispatch may
not have. The restart runs under its starter's right (owner or
``images.manage``, recorded on the record): it is re-checked when a runner
starts and before each later chunk, and a lost right finishes the restart.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import select, update

from sm_images.access.starter_right import holds_right
from sm_images.clock import utcnow as _now
from sm_images.constants import NO_SYNC
from sm_images.models import Image, PipelineRestart
from sm_images.pipeline.orchestrate import Scope, reset_image, submit_dispatch
from sm_images.pipeline.runtime import Runtime

__all__ = ["CHUNK", "restart_collection_async", "resume_restart", "start_restart"]

logger = logging.getLogger(__name__)

CHUNK = 1000


async def start_restart(
    runtime: Runtime,
    tenant: str,
    collection_id: uuid.UUID,
    scope: Scope,
    *,
    run_as: str | None = None,
    access_basis: str | None = None,
) -> uuid.UUID:
    async with runtime.session_factory() as db:
        row = PipelineRestart(
            collection_id=collection_id,
            scope=scope,
            heartbeat_at=_now(),
            run_as=run_as,
            access_basis=access_basis,
        )
        db.add(row)
        await finalize_session(db)
        return row.id


async def _chunk(
    runtime: Runtime, tenant: str, collection_id: uuid.UUID, after: Any, size: int
) -> list[uuid.UUID]:
    stmt = (
        select(Image.id)
        .where(Image.collection_id == collection_id, Image.tenant_id == tenant)
        .order_by(Image.id)
        .limit(size)
    )
    if after is not None:
        stmt = stmt.where(Image.id > after)
    async with runtime.session_factory() as db:
        ids = list((await db.execute(stmt)).scalars())
        await finalize_session(db)
    return ids


def _record(tenant: str, restart_id: uuid.UUID) -> list[Any]:
    return [PipelineRestart.id == restart_id, PipelineRestart.tenant_id == tenant]


async def _advance(db: Any, tenant: str, restart_id: uuid.UUID, prev: Any, image_id: Any) -> bool:
    at = PipelineRestart.cursor.is_(None) if prev is None else PipelineRestart.cursor == prev
    stmt = (
        update(PipelineRestart)
        .where(*_record(tenant, restart_id), PipelineRestart.finished_at.is_(None), at)
        .values(cursor=image_id, heartbeat_at=_now())
        .returning(PipelineRestart.id)
        .execution_options(**NO_SYNC)
    )
    return (await db.execute(stmt)).first() is not None


async def resume_restart(
    runtime: Runtime, tenant: str, restart_id: uuid.UUID, *, chunk: int = CHUNK
) -> int:
    """Carry restart ``restart_id`` on from its cursor; returns images changed."""
    async with runtime.session_factory() as db:
        stmt = select(PipelineRestart).where(*_record(tenant, restart_id))
        row = (await db.execute(stmt)).scalar_one_or_none()
        found = None if row is None else (row.collection_id, row.scope, row.cursor, row.finished_at)
        starter = None if row is None else (row.run_as, row.access_basis)
        await finalize_session(db)
    if found is None or found[3] is not None or starter is None:
        return 0
    collection_id, scope, after, _ = found

    async def allowed() -> bool:
        return await holds_right(runtime, tenant, collection_id, *starter, shares=False)

    if not await allowed():
        return await _finish(runtime, tenant, restart_id, 0, revoked=True)
    if after is not None:
        await submit_dispatch(runtime, tenant, after)
    size = max(1, min(chunk, CHUNK))
    changed, first = 0, True
    while ids := await _chunk(runtime, tenant, collection_id, after, size):
        if not first and not await allowed():  # re-checked before every later chunk
            return await _finish(runtime, tenant, restart_id, changed, revoked=True)
        first = False
        for image_id in ids:
            async with runtime.session_factory() as db:
                if not await _advance(db, tenant, restart_id, after, image_id):
                    await db.rollback()
                    return changed  # another runner got here first
                changed += bool(await reset_image(db, tenant, image_id, scope))
                await finalize_session(db)
            after = image_id
            await submit_dispatch(runtime, tenant, image_id)
    return await _finish(runtime, tenant, restart_id, changed)


async def _finish(
    runtime: Runtime, tenant: str, restart_id: uuid.UUID, changed: int, *, revoked: bool = False
) -> int:
    """Mark the restart finished (so reconcile never resumes it); *changed*."""
    async with runtime.session_factory() as db:
        await db.execute(
            update(PipelineRestart)
            .where(*_record(tenant, restart_id))
            .values(finished_at=_now(), heartbeat_at=_now())
            .execution_options(**NO_SYNC)
        )
        await finalize_session(db)
    if revoked:
        logger.info("images.restart.access_revoked restart=%s", restart_id)
    return changed


async def restart_collection_async(
    runtime: Runtime,
    tenant: str,
    collection_id: uuid.UUID,
    scope: Scope,
    *,
    chunk: int = CHUNK,
    restart_id: uuid.UUID | None = None,
    run_as: str | None = None,
    access_basis: str | None = None,
) -> int:
    """Record (or continue) a restart of ``collection_id`` and run it."""
    if restart_id is None:
        restart_id = await start_restart(
            runtime, tenant, collection_id, scope, run_as=run_as, access_basis=access_basis
        )
    return await resume_restart(runtime, tenant, restart_id, chunk=chunk)
