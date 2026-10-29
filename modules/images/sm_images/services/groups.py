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

from sqlalchemy import case, delete, exists, func, literal, select, update
from sqlalchemy.exc import IntegrityError

from sm_images import constants, redaction
from sm_images.errors import Conflict, GroupExists, InvalidGroup, NotFound
from sm_images.imports.filename_pattern import canonical_role
from sm_images.map import schedule as map_schedule
from sm_images.models import Collection, Group, Image

__all__ = [
    "assign",
    "counts",
    "create",
    "delete_group",
    "get",
    "list_page",
    "member_order",
    "members",
    "update_group",
]

_NO_GROUP = "That group does not exist in this collection"
_NEEDS_GROUP = "A role can only be set on an image that is in a group"
_MOVED = "The image changed while it was being edited; reload and try again"
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


def _has_ready_member(collection: Collection) -> Any:
    """A group's key comes from the metadata of its images, so a group of
    withheld images is withheld too."""
    return exists(
        select(Image.id).where(Image.group_id == Group.id, redaction.ready_clause(collection))
    )


async def get(
    db: Any, collection: Collection, group_id: uuid.UUID, *, gated: bool = False
) -> Group:
    stmt = select(Group).where(Group.id == group_id, Group.collection_id == collection.id)
    if gated:
        stmt = stmt.where(_has_ready_member(collection))
    found = (await db.execute(stmt)).scalars().first()
    if found is None:
        raise NotFound(constants.NOT_FOUND_DETAIL)
    return found


async def counts(
    db: Any, groups: Sequence[Group], *, gate: Collection | None = None
) -> dict[uuid.UUID, int]:
    """Members per group (trashed images excluded). With ``gate`` (a viewer's
    read of that collection) only display-safe images count."""
    if not groups:
        return {}
    stmt = (
        select(Image.group_id, func.count())
        .where(Image.group_id.in_([g.id for g in groups]))
        .group_by(Image.group_id)
    )
    if gate is not None:
        stmt = stmt.where(redaction.ready_clause(gate))
    return {gid: int(n) for gid, n in (await db.execute(stmt)).all()}


async def members(
    db: Any,
    collection: Collection,
    group_ids: Sequence[uuid.UUID],
    per_group: int,
    *,
    gated: bool = False,
) -> dict[uuid.UUID, list[Image]]:
    """The first ``per_group`` members of each group, in role order (only the
    display-safe ones when ``gated``)."""
    if not group_ids:
        return {}
    ordering = member_order(list(collection.group_roles or []))
    numbered = select(
        Image.id.label("iid"),
        func.row_number().over(partition_by=Image.group_id, order_by=ordering).label("rn"),
    ).where(Image.collection_id == collection.id, Image.group_id.in_(group_ids))
    if gated:
        numbered = numbered.where(redaction.ready_clause(collection))
    numbered = numbered.subquery()
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
    db: Any, collection: Collection, *, limit: int, after: str | None, gated: bool = False
) -> tuple[list[Group], str | None]:
    """Groups by key; ``after`` is the last key of the previous page. ``gated``
    (a viewer) keeps only groups with a display-safe member, before paging."""
    stmt = select(Group).where(Group.collection_id == collection.id)
    if gated:
        stmt = stmt.where(_has_ready_member(collection))
    if after is not None:
        stmt = stmt.where(Group.key > after)
    rows = list((await db.execute(stmt.order_by(Group.key).limit(limit + 1))).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    return rows, rows[-1].key if more else None


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
    freed = await db.execute(
        update(Image)
        .where(Image.collection_id == collection.id, Image.group_id == group.id)
        .values(group_id=None, group_role=None)
        .execution_options(include_deleted=True, synchronize_session=False)
    )
    await map_schedule.changed(db, collection.id, count=int(freed.rowcount or 0))
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
            raise InvalidGroup(_NEEDS_GROUP, constants.CODE_ROLE_NEEDS_GROUP)
        role = None
    elif set_role:
        role = _role(collection, group_role)
    result = await db.execute(
        update(Image)
        .where(
            Image.id == image.id,
            Image.collection_id == collection.id,
            Image.group_id.is_not_distinct_from(image.group_id),
            Image.group_role.is_not_distinct_from(image.group_role),
        )
        .values(group_id=target, group_role=role)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # someone else moved or re-roled it since we read it
        err = Conflict(_MOVED)
        err.code = constants.CODE_CONFLICT
        raise err
    if target != image.group_id:  # the point's group_id
        await map_schedule.changed(db, collection.id)
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
