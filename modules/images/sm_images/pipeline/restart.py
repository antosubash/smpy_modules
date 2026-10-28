"""Re-run a whole collection: ``images.restart_collection``'s body.

Keyset over the collection's live images in chunks of at most 1000, so memory
stays bounded however large the collection is. Each image is reset in its own
short transaction (its lock, then its runs - the executor's lock order) and
dispatched; an image with a run someone holds a live lease on keeps that run
and does not hold the others back.
"""

from __future__ import annotations

import uuid
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import select

from sm_images.models import Image
from sm_images.pipeline.orchestrate import Scope, reset_image, submit_dispatch
from sm_images.pipeline.runtime import Runtime

__all__ = ["CHUNK", "restart_collection_async"]

CHUNK = 1000


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


async def restart_collection_async(
    runtime: Runtime, tenant: str, collection_id: uuid.UUID, scope: Scope, *, chunk: int = CHUNK
) -> int:
    """Reset ``scope`` on every image and dispatch each; returns how many changed."""
    size = max(1, min(chunk, CHUNK))
    changed = 0
    after = None
    while ids := await _chunk(runtime, tenant, collection_id, after, size):
        for image_id in ids:
            async with runtime.session_factory() as db:
                changed += bool(await reset_image(db, tenant, image_id, scope))
                await finalize_session(db)
            await submit_dispatch(runtime, tenant, image_id)
        after = ids[-1]
    return changed
