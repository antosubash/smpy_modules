"""Writing a regroup: resolve the groups a chunk names, then assign its images.

The write half of :mod:`sm_images.services.regroup`, shared by the in-request
path and the background job (:mod:`sm_images.regroup`):

* :func:`ensure_groups` creates the missing groups with ``ON CONFLICT DO
  NOTHING``, so a competing insert is told apart from one's own;
* :func:`apply_chunk` is one ``UPDATE ... CASE`` per chunk, counted by the rows
  it actually changed;
* :func:`settle` runs both for a list of planned changes (or only counts, for a
  preview).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Uuid, case, literal, select, update

from sm_images import constants
from sm_images.clock.db import dialect_insert
from sm_images.map import schedule as map_schedule
from sm_images.models import Group, Image

__all__ = ["Change", "apply_chunk", "ensure_groups", "keys_to_ids", "settle"]

Change = tuple[uuid.UUID, str, str | None]
"""``(image_id, group_key, role-or-None-to-keep)``."""


async def keys_to_ids(
    db: Any, collection_id: uuid.UUID, keys: Sequence[str]
) -> dict[str, uuid.UUID]:
    stmt = select(Group.key, Group.id).where(
        Group.collection_id == collection_id, Group.key.in_(list(keys))
    )
    return dict((await db.execute(stmt)).all())


async def ensure_groups(
    db: Any,
    tenant: str,
    collection_id: uuid.UUID,
    keys: Sequence[str],
    since: datetime | None = None,
) -> tuple[dict[str, uuid.UUID], int, list[uuid.UUID]]:
    """``(key -> group id, created, existing ids)`` for ``keys``.

    ``created`` counts only the rows this call inserted: a key another writer
    inserted between the read and the insert comes back from ``ON CONFLICT DO
    NOTHING`` without a row, so it is not ours. ``existing`` lists the groups
    not inserted here that were already there when the regroup began (``since``;
    ``None`` = all of them) - a group an earlier chunk of the same job made is
    neither.
    """
    ids: dict[str, uuid.UUID] = {}
    inserted_keys: set[str] = set()
    for i in range(0, len(keys), constants.REGROUP_CHUNK):
        batch = list(keys[i : i + constants.REGROUP_CHUNK])
        ids.update(await keys_to_ids(db, collection_id, batch))
        missing = [k for k in batch if k not in ids]
        if not missing:
            continue
        stamp = datetime.now(UTC)
        rows = [
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant,
                "collection_id": collection_id,
                "key": k,
                "created_at": stamp,
                "updated_at": stamp,
            }
            for k in missing
        ]
        stmt = (
            dialect_insert(db)(Group)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["collection_id", "key"])
            .returning(Group.key, Group.id)
        )
        inserted = dict((await db.execute(stmt)).all())
        inserted_keys.update(inserted)
        ids.update(inserted)
        lost = [k for k in missing if k not in inserted]
        if lost:
            ids.update(await keys_to_ids(db, collection_id, lost))
    others = [k for k in keys if k not in inserted_keys]
    if since is None:
        return ids, len(inserted_keys), [ids[k] for k in others]
    stmt = select(Group.id).where(
        Group.collection_id == collection_id,
        Group.key.in_(others),
        Group.created_at < since,
    )
    return ids, len(inserted_keys), list((await db.execute(stmt)).scalars()) if others else []


async def apply_chunk(
    db: Any,
    collection_id: uuid.UUID,
    changes: Sequence[Change],
    groups: dict[str, uuid.UUID],
    reassign: bool,
) -> int:
    """Write ``changes`` and return how many rows changed (not how many were planned)."""
    if not changes:
        return 0
    ids = [c[0] for c in changes]
    # typed literals: asyncpg would send bare UUIDs in a CASE as text
    group_case = case({c[0]: literal(groups[c[1]], Uuid()) for c in changes}, value=Image.id)
    roles = {c[0]: c[2] for c in changes if c[2] is not None}
    role_case = case(roles, value=Image.id, else_=Image.group_role) if roles else Image.group_role
    stmt = update(Image).where(Image.id.in_(ids), Image.collection_id == collection_id)
    if not reassign:
        stmt = stmt.where(Image.group_id.is_(None))  # lost a race to a manual assignment
    result = await db.execute(
        stmt.values(group_id=group_case, group_role=role_case).execution_options(
            synchronize_session=False
        )
    )
    return int(result.rowcount)


async def settle(
    db: Any,
    tenant: str,
    collection_id: uuid.UUID,
    changes: Sequence[Change],
    *,
    reassign: bool,
    dry_run: bool,
    since: datetime | None = None,
) -> tuple[int, int, list[uuid.UUID]]:
    """Resolve the groups ``changes`` name and write them (``dry_run``: only
    count). Returns ``(assigned, groups_created, existing group ids)``;
    ``assigned`` is the rows actually changed."""
    if not changes:
        return 0, 0, []
    keys = sorted({c[1] for c in changes})
    if dry_run:
        known = await keys_to_ids(db, collection_id, keys)
        return len(changes), len(keys) - len(known), list(known.values())
    groups, created, existing = await ensure_groups(db, tenant, collection_id, keys, since)
    assigned = 0
    for i in range(0, len(changes), constants.REGROUP_CHUNK):
        part = changes[i : i + constants.REGROUP_CHUNK]
        assigned += await apply_chunk(db, collection_id, part, groups, reassign)
    await map_schedule.changed(db, collection_id, count=assigned)  # each point's group_id
    return assigned, created, existing
