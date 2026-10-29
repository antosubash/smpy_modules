"""A collection's groups: list, create, rename, delete, and a member's assignment.

Like :mod:`sm_images.services.gallery`, every statement is pinned to the
collection the caller already loaded through the access policy. Members are
ordered by the collection's ``group_roles`` (:func:`member_order`); a role the
collection does not list sorts after the listed ones, then by role name, then
by ``created_at``. Nothing here knows a role by name.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import case, delete, func, literal, select, update
from sqlalchemy.exc import IntegrityError

from sm_images import constants
from sm_images.errors import GroupExists, InvalidGroup, NotFound
from sm_images.imports.filename_pattern import canonical_role
from sm_images.models import Collection, Group, Image

__all__ = [
    "assign",
    "create",
    "delete_group",
    "ensure_free_key",
    "get",
    "list_page",
    "member_order",
    "members",
    "update_group",
]

_NO_GROUP = "That group does not exist in this collection"
_BAD_ROLE = "That role is not one of the collection's group roles"


def member_order(roles: Sequence[str]) -> list[Any]:
    """``ORDER BY`` for a group's members: listed roles in their order, the rest
    after them (role-less last), then role name, creation time and id."""
    rank = (
        case({r: i for i, r in enumerate(roles)}, value=Image.group_role, else_=len(roles))
        if roles
        else literal(0)
    )
    return [rank, Image.group_role.is_(None), Image.group_role, Image.created_at, Image.id]


async def get(db: Any, collection: Collection, group_id: uuid.UUID) -> Group:
    stmt = select(Group).where(Group.id == group_id, Group.collection_id == collection.id)
    found = (await db.execute(stmt)).scalars().first()
    if found is None:
        raise NotFound(constants.NOT_FOUND_DETAIL)
    return found


async def _counts(db: Any, group_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    stmt = (
        select(Image.group_id, func.count())
        .where(Image.group_id.in_(group_ids))
        .group_by(Image.group_id)
    )
    return {gid: int(n) for gid, n in (await db.execute(stmt)).all()}


async def members(
    db: Any, collection: Collection, group_ids: Sequence[uuid.UUID], per_group: int
) -> dict[uuid.UUID, list[Image]]:
    """The first ``per_group`` members of each group, in role order."""
    if not group_ids:
        return {}
    ordering = member_order(list(collection.group_roles or []))
    numbered = (
        select(
            Image.id.label("iid"),
            func.row_number().over(partition_by=Image.group_id, order_by=ordering).label("rn"),
        )
        .where(Image.collection_id == collection.id, Image.group_id.in_(group_ids))
        .subquery()
    )
    stmt = (
        select(Image)
        .join(numbered, numbered.c.iid == Image.id)
        .where(numbered.c.rn <= per_group)
        .order_by(Image.group_id, numbered.c.rn)
    )
    out: dict[uuid.UUID, list[Image]] = {gid: [] for gid in group_ids}
    for row in (await db.execute(stmt)).scalars():
        out[row.group_id].append(row)
    return out


async def list_page(
    db: Any, collection: Collection, *, limit: int, after: str | None
) -> tuple[list[Group], str | None]:
    """Groups by key; ``after`` is the last key of the previous page."""
    stmt = select(Group).where(Group.collection_id == collection.id)
    if after is not None:
        stmt = stmt.where(Group.key > after)
    rows = list((await db.execute(stmt.order_by(Group.key).limit(limit + 1))).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    return rows, rows[-1].key if more else None


async def counts(db: Any, groups: Sequence[Group]) -> dict[uuid.UUID, int]:
    return await _counts(db, [g.id for g in groups]) if groups else {}


async def _key_taken(
    db: Any, collection: Collection, key: str, *, not_id: uuid.UUID | None
) -> bool:
    stmt = select(Group.id).where(Group.collection_id == collection.id, Group.key == key)
    if not_id is not None:
        stmt = stmt.where(Group.id != not_id)
    return (await db.execute(stmt.limit(1))).first() is not None


async def ensure_free_key(
    db: Any, collection: Collection, key: str, *, not_id: uuid.UUID | None = None
) -> None:
    if await _key_taken(db, collection, key, not_id=not_id):
        raise GroupExists(constants.GROUP_EXISTS_DETAIL)


async def create(
    db: Any, collection: Collection, *, key: str, name: str | None, description: str | None
) -> Group:
    await ensure_free_key(db, collection, key)
    group = Group(collection_id=collection.id, key=key, name=name, description=description)
    try:
        async with db.begin_nested():
            db.add(group)
            await db.flush()
    except IntegrityError:
        raise GroupExists(constants.GROUP_EXISTS_DETAIL) from None
    return group


async def update_group(
    db: Any, collection: Collection, group: Group, fields: dict[str, Any]
) -> Group:
    """Apply the fields the client sent. A new key must be free in the collection."""
    if fields.get("key") not in (None, group.key):
        await ensure_free_key(db, collection, fields["key"], not_id=group.id)
    if fields.get("key") is None:
        fields.pop("key", None)
    for name, value in fields.items():
        setattr(group, name, value)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        raise GroupExists(constants.GROUP_EXISTS_DETAIL) from None
    return group


async def delete_group(db: Any, collection: Collection, group: Group) -> None:
    """Free the members first (``images_image.group_id`` has no ``ON DELETE``),
    trashed ones too, then drop the group."""
    await db.execute(
        update(Image)
        .where(Image.collection_id == collection.id, Image.group_id == group.id)
        .values(group_id=None, group_role=None)
        .execution_options(include_deleted=True, synchronize_session=False)
    )
    await db.execute(
        delete(Group)
        .where(Group.id == group.id, Group.collection_id == collection.id)
        .execution_options(synchronize_session=False)
    )
    db.expunge(group)


async def assign(
    db: Any,
    collection: Collection,
    image: Image,
    *,
    group_id: uuid.UUID | None,
    group_role: str | None,
    set_group: bool,
    set_role: bool,
) -> Image:
    """Move ``image`` into a group of its own collection and/or set its role.

    Clearing the group clears the role. A role is canonicalised against the
    collection's ``group_roles`` (case-insensitive, stored in the collection's
    spelling) and refused when the collection lists roles and this is not one.
    """
    target = image.group_id
    if set_group:
        target = group_id
        if target is not None:
            await _require_group(db, collection, target)
    role = image.group_role
    if target is None:
        if set_role and group_role is not None:
            raise InvalidGroup(_NO_GROUP, constants.CODE_GROUP_NOT_FOUND)
        role = None
    elif set_role:
        role = _role(collection, group_role)
    await db.execute(
        update(Image)
        .where(Image.id == image.id, Image.collection_id == collection.id)
        .values(group_id=target, group_role=role)
        .execution_options(synchronize_session=False)
    )
    await db.refresh(image)
    return image


async def _require_group(db: Any, collection: Collection, group_id: uuid.UUID) -> None:
    stmt = select(Group.id).where(Group.id == group_id, Group.collection_id == collection.id)
    if (await db.execute(stmt)).first() is None:
        raise InvalidGroup(_NO_GROUP, constants.CODE_GROUP_NOT_FOUND)


def _role(collection: Collection, raw: str | None) -> str | None:
    if raw is None:
        return None
    role = canonical_role(raw, list(collection.group_roles or []))
    if role is None:
        raise InvalidGroup(_BAD_ROLE, constants.CODE_INVALID_ROLE)
    return role
