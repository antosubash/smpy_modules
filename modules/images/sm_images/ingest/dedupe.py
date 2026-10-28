"""The lookups behind ingest's dedupe, and find-or-create for groups.

External identity is ``(collection_id, external_source, external_id)``, unique
in the database (``uq_images_image_external``) **including trashed rows**: the
index is not partial on ``is_deleted``, so both lookups read through the trash,
and a re-upload of a trashed image's id is a duplicate of that image rather
than an ``IntegrityError`` nobody explains.

Three layers (porting map, "Single/batch/base64 uploads"): the pre-check here,
the per-service in-batch set (``IngestService``), and, for the race both miss,
the unique index - after whose ``IntegrityError`` :func:`find_external` is asked
again, so a concurrent duplicate answers ``duplicate`` instead of a 500.

Content-hash dedupe (``dedupe_by_hash``, off by default) has no index behind it:
two concurrent uploads of the same bytes can both land. It is a convenience,
not an invariant.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sm_images.models import Group, Image

__all__ = ["ensure_group", "find_external", "find_hash", "find_id"]


async def find_external(
    db: Any, collection_id: uuid.UUID, source: str, external_id: str
) -> uuid.UUID | None:
    stmt = (
        select(Image.id)
        .where(
            Image.collection_id == collection_id,
            Image.external_source == source,
            Image.external_id == external_id,
        )
        .execution_options(include_deleted=True)
    )
    return (await db.execute(stmt)).scalars().first()


async def find_id(db: Any, image_id: uuid.UUID | None) -> bool:
    """Whether a row (trashed or not) already owns ``image_id``."""
    if image_id is None:
        return False
    stmt = select(Image.id).where(Image.id == image_id).execution_options(include_deleted=True)
    return (await db.execute(stmt)).scalars().first() is not None


async def find_hash(db: Any, collection_id: uuid.UUID, sha256: str) -> uuid.UUID | None:
    stmt = select(Image.id).where(Image.collection_id == collection_id, Image.sha256 == sha256)
    return (await db.execute(stmt.limit(1))).scalars().first()


async def _group_id(db: Any, collection_id: uuid.UUID, key: str) -> uuid.UUID | None:
    stmt = select(Group.id).where(Group.collection_id == collection_id, Group.key == key)
    return (await db.execute(stmt)).scalars().first()


async def ensure_group(db: Any, collection_id: uuid.UUID, key: str) -> uuid.UUID:
    """The group ``key`` names in the collection, created on first use.

    The create runs in its own savepoint so losing the race to a concurrent
    upload of the same group costs only that savepoint, then reads the winner.
    """
    found = await _group_id(db, collection_id, key)
    if found is not None:
        return found
    group = Group(collection_id=collection_id, key=key)
    try:
        async with db.begin_nested():
            db.add(group)
            await db.flush()
    except IntegrityError:
        found = await _group_id(db, collection_id, key)
        if found is None:
            raise
        return found
    return group.id
