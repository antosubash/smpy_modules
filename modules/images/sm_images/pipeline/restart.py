"""Re-run a whole collection: ``images.restart_collection``'s body.

A restart is a durable record (:class:`PipelineRestart`), so one lost to a
dead worker or a lost message is finished by ``images.reconcile``. Images are
walked by keyset in chunks of at most 1000. Each image is reset in its own
short transaction that also advances the record's cursor *conditionally on
its previous value* - so an image is reset at most once per restart, even with
two runners on one record, and a runner that lost that race stops. Resuming
re-dispatches the cursor's image first: its reset committed, its dispatch may
not have.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import select, update

from sm_images.models import Image, PipelineRestart
from sm_images.pipeline.orchestrate import Scope, reset_image, submit_dispatch
from sm_images.pipeline.runtime import Runtime

__all__ = ["CHUNK", "restart_collection_async", "resume_restart", "start_restart"]

CHUNK = 1000
_SYNC = {"synchronize_session": False}


def _now() -> datetime:
    return datetime.now(UTC)


async def start_restart(
    runtime: Runtime, tenant: str, collection_id: uuid.UUID, scope: Scope
) -> uuid.UUID:
    async with runtime.session_factory() as db:
        row = PipelineRestart(collection_id=collection_id, scope=scope, heartbeat_at=_now())
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
        .execution_options(**_SYNC)
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
        await finalize_session(db)
    if found is None or found[3] is not None:
        return 0
    collection_id, scope, after, _ = found
    if after is not None:
        await submit_dispatch(runtime, tenant, after)
    size = max(1, min(chunk, CHUNK))
    changed = 0
    while ids := await _chunk(runtime, tenant, collection_id, after, size):
        for image_id in ids:
            async with runtime.session_factory() as db:
                if not await _advance(db, tenant, restart_id, after, image_id):
                    await db.rollback()
                    return changed  # another runner got here first
                changed += bool(await reset_image(db, tenant, image_id, scope))
                await finalize_session(db)
            after = image_id
            await submit_dispatch(runtime, tenant, image_id)
    async with runtime.session_factory() as db:
        await db.execute(
            update(PipelineRestart)
            .where(*_record(tenant, restart_id))
            .values(finished_at=_now(), heartbeat_at=_now())
            .execution_options(**_SYNC)
        )
        await finalize_session(db)
    return changed


async def restart_collection_async(
    runtime: Runtime,
    tenant: str,
    collection_id: uuid.UUID,
    scope: Scope,
    *,
    chunk: int = CHUNK,
    restart_id: uuid.UUID | None = None,
) -> int:
    """Record (or continue) a restart of ``collection_id`` and run it."""
    if restart_id is None:
        restart_id = await start_restart(runtime, tenant, collection_id, scope)
    return await resume_restart(runtime, tenant, restart_id, chunk=chunk)
