"""The access matrix's cast, collections and a test-only router.

Collection routes arrive with Task 6, so the policy is exercised through a
router that exists only here: a list over :func:`visible_collections` and a
detail, edit and delete route behind ``CollectionView``/``CollectionEdit``/
``CollectionOwner``, plus one anonymous route behind :func:`public_collection`.
Mounted with the module's own tenant bindings, as Task 6's routers will be.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from sharing.models import ResourceShare
from sharing.policy import canonical_id
from simple_module_core.resources import ACTION_VIEW, ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import resource_principal
from sm_images.access import (
    COLLECTION_RESOURCE,
    CollectionEdit,
    CollectionOwner,
    CollectionView,
    public_collection,
    visible_collections,
)
from sm_images.models import Collection, Image, Visibility
from sm_images.tenancy import bind_admin, bind_public

from tests.stub_auth import as_user, user_uuid

ADMIN_BASE = "/_access/collections"
PUBLIC_BASE = "/_access/public"

OWNER, STRANGER, VIEWER, EDITOR, MANAGER = "olga", "sam", "vic", "eddie", "max"
PERMS: dict[str, tuple[str, ...]] = {
    OWNER: ("images.view",),
    STRANGER: ("images.view",),
    VIEWER: ("images.view",),
    EDITOR: ("images.view",),
    MANAGER: ("images.view", "images.manage"),
}
ANON = None
CALLERS = (OWNER, STRANGER, VIEWER, EDITOR, MANAGER, ANON)


def headers(who: str | None, tenant: str | None = None) -> dict[str, str]:
    return {} if who is None else as_user(who, PERMS.get(who, ()), tenant)


def principal(who: str | None) -> ResourcePrincipal:
    """The principal ``resource_principal`` builds for the same header user."""
    if who is None:
        return ResourcePrincipal(user_id=None)
    return ResourcePrincipal(user_id=user_uuid(who), permissions=frozenset(PERMS[who]))


def build_router() -> tuple[APIRouter, APIRouter]:
    admin = APIRouter(prefix=ADMIN_BASE, dependencies=[Depends(bind_admin)])

    @admin.get("")
    async def listing(
        who: ResourcePrincipal = Depends(resource_principal), db: Any = Depends(get_db)
    ) -> list[str]:
        rows = (await db.execute(visible_collections(who, ACTION_VIEW))).scalars().all()
        return sorted(row.slug for row in rows)

    @admin.get("/{collection_id}")
    async def detail(collection: CollectionView) -> dict[str, str]:
        return {"slug": collection.slug}

    @admin.post("/{collection_id}/images")
    async def upload(collection: CollectionEdit) -> dict[str, str]:
        return {"slug": collection.slug}

    @admin.delete("/{collection_id}")
    async def delete(collection: CollectionOwner) -> dict[str, str]:
        return {"slug": collection.slug}

    public = APIRouter(prefix=PUBLIC_BASE, dependencies=[Depends(bind_public)])

    @public.get("/c/{slug}")
    async def public_page(collection: Collection = Depends(public_collection)) -> dict[str, str]:
        return {"slug": collection.slug}

    return admin, public


def mount(app: FastAPI) -> None:
    for router in build_router():
        app.include_router(router)


def collection(slug: str, visibility: Visibility, owner: str = OWNER, **kw: Any) -> Collection:
    return Collection(slug=slug, name=slug, owner_id=user_uuid(owner), visibility=visibility, **kw)


def image(coll: Collection, name: str, **kw: Any) -> Image:
    return Image(
        collection_id=coll.id,
        storage_key=f"k/{name}",
        filename=name,
        content_type="image/jpeg",
        size_bytes=1,
        **kw,
    )


def share(coll: Collection, who: str, role: str, **kw: Any) -> ResourceShare:
    return ResourceShare(
        resource_type=COLLECTION_RESOURCE,
        resource_id=canonical_id(coll.id),
        subject_type="user",
        subject_id=user_uuid(who),
        role=role,
        granted_by=user_uuid(OWNER),
        **kw,
    )


async def seed_matrix(session_factory: Any) -> dict[str, uuid.UUID]:
    """``priv``/``int``/``pub`` owned by olga, plus a trashed public one.

    ``priv`` is shared with vic (view) and eddie (edit); an expired edit share
    gives sam nothing.
    """
    from datetime import UTC, datetime, timedelta

    priv = collection("priv", Visibility.PRIVATE)
    internal = collection("int", Visibility.INTERNAL)
    pub = collection("pub", Visibility.PUBLIC)
    gone = collection("gone", Visibility.PUBLIC, is_deleted=True)
    async with session_factory() as s:
        s.add_all([priv, internal, pub, gone])
        await s.flush()
        s.add_all(
            [
                share(priv, VIEWER, "view"),
                share(priv, EDITOR, "edit"),
                share(priv, STRANGER, "edit", expires_at=datetime.now(UTC) - timedelta(days=1)),
                share(gone, EDITOR, "edit"),
            ]
        )
        await s.commit()
    return {"priv": priv.id, "int": internal.id, "pub": pub.id, "gone": gone.id}
