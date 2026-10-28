"""Collection CRUD and listing. No FastAPI here: failures are ``ImagesError``."""

from __future__ import annotations

import secrets
from typing import Any

from sharing.policy import share_exists_for
from simple_module_core.resources import ACTION_VIEW, ResourcePrincipal
from sqlalchemy import false, func, select
from sqlalchemy.exc import IntegrityError

from sm_images import constants
from sm_images.access import COLLECTION_RESOURCE, POLICY
from sm_images.errors import Conflict, Forbidden, Invalid
from sm_images.models import Collection, Visibility
from sm_images.models.collection import COLLECTION_SLUG_INDEX
from sm_images.services import cursor as cursors
from sm_images.services.slugs import slugify

__all__ = [
    "create",
    "list_page",
    "require_publish",
    "set_visibility",
    "update",
]

_SHARES = share_exists_for(COLLECTION_RESOURCE, Collection.id)


def require_publish(who: ResourcePrincipal, target: Visibility) -> None:
    if target is not Visibility.PRIVATE and not (
        who.has(constants.PERM_PUBLISH) or who.has(constants.PERM_MANAGE)
    ):
        raise Forbidden(constants.PUBLISH_REQUIRED_DETAIL)


async def _slug_taken(db: Any, slug: str) -> bool:
    # Trashed rows keep their slug: the unique index covers them.
    stmt = select(func.count()).select_from(Collection).where(Collection.slug == slug)
    return bool((await db.execute(stmt.execution_options(include_deleted=True))).scalar_one())


async def _free_slug(db: Any, name: str) -> str:
    base = slugify(name)
    slug = base
    while await _slug_taken(db, slug):
        suffix = secrets.token_hex(2)
        slug = f"{base[: constants.SLUG_MAX - len(suffix) - 1].rstrip('-')}-{suffix}"
    return slug


async def create(
    db: Any,
    who: ResourcePrincipal,
    *,
    name: str,
    description: str | None,
    slug: str | None,
    visibility: Visibility,
) -> Collection:
    """Insert a collection owned by *who*. An explicit slug that is taken is a
    409; one generated from the name gets a short suffix instead."""
    require_publish(who, visibility)
    if who.user_id is None:
        raise Forbidden("A signed-in user is required")
    if slug is not None and await _slug_taken(db, slug):
        raise Conflict(constants.SLUG_TAKEN_DETAIL)
    row = Collection(
        slug=slug or await _free_slug(db, name),
        name=name,
        description=description,
        owner_id=who.user_id,
        visibility=visibility,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:  # lost a race for the slug
        if COLLECTION_SLUG_INDEX not in str(exc.orig) and "slug" not in str(exc.orig):
            raise
        raise Conflict(constants.SLUG_TAKEN_DETAIL) from exc
    return row


def update(row: Collection, fields: dict[str, Any]) -> Collection:
    """Apply a PATCH. ``fields`` is the body's *set* fields; an explicit
    ``null`` name is ignored because the column is NOT NULL."""
    if fields.get("name") is not None:
        row.name = fields["name"]
    if "description" in fields:
        row.description = fields["description"]
    return row


def set_visibility(row: Collection, who: ResourcePrincipal, target: Visibility) -> Visibility:
    """Move *row* to *target*; returns the visibility it had. The caller has
    already established owner-or-manager through ``CollectionOwner``."""
    before = row.visibility
    if before is not target:
        require_publish(who, target)
        row.visibility = target
    return before


def _filter_clause(name: str, who: ResourcePrincipal) -> Any:
    if name == "all":
        return None
    if name == "internal":
        return Collection.visibility == Visibility.INTERNAL
    if name == "public":
        return Collection.visibility == Visibility.PUBLIC
    if who.user_id is None:
        return false()
    if name == "owned":
        return Collection.owner_id == who.user_id
    if name == "shared":
        shared = _SHARES(who, ACTION_VIEW)
        return false() if shared is None else (shared & (Collection.owner_id != who.user_id))
    raise Invalid(f"unknown filter {name!r}")


async def list_page(
    db: Any,
    who: ResourcePrincipal,
    *,
    filter_: str = "all",
    limit: int = constants.PAGE_DEFAULT,
    cursor: str | None = None,
) -> tuple[list[Collection], str | None, int | None]:
    """``(rows, next_cursor, total)``; ``total`` is counted on the first page
    only. Every filter is ANDed with the view policy, in SQL."""
    stmt = POLICY.filter(who, ACTION_VIEW, select(Collection))
    extra = _filter_clause(filter_, who)
    if extra is not None:
        stmt = stmt.where(extra)
    total = None
    if cursor is None:
        total = int(
            (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
    else:
        stmt = stmt.where(cursors.seek(Collection.created_at, Collection.id, cursor))
    stmt = stmt.order_by(Collection.created_at.desc(), Collection.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    token = cursors.encode(rows[-1].created_at, rows[-1].id) if more else None
    return rows, token, total
