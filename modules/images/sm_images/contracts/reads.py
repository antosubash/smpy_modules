"""Policy-filtered reads for other modules (spec §7).

**Every call names its tenant** and binds it with ``tenant_scope`` for the
duration, so a caller that has no tenant bound (a worker, another module's
beat task) still reads exactly one. A caller already inside a *different*
tenant is refused rather than re-bound.

**Every call names its principal** and goes through
:data:`sm_images.access.POLICY` for ``view``: a module asking for "the
collections of this user" sees what that user would see in the console, and a
collection they may not open is ``None``, indistinguishable from one that does
not exist.

**A session is optional.** Pass the caller's own (``db=``) to join its unit of
work, as pagebuilder's contracts do; without one the call opens a short
read-only session from the factory ``on_startup`` registered
(:func:`sm_images.intents.current_factory`) and rolls it back on the way out.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from simple_module_core.resources import ACTION_VIEW, ResourcePrincipal
from sqlalchemy import select

from sm_images import constants, intents, urls
from sm_images.access import POLICY
from sm_images.contracts.schemas import CollectionPageRead, CollectionRead
from sm_images.models import Collection
from sm_images.services import collections as service
from sm_images.tenancy import tenant_scope

__all__ = ["get_collection", "list_collections", "rendition_url"]


@asynccontextmanager
async def _session(db: Any) -> AsyncIterator[Any]:
    if db is not None:
        yield db
        return
    async with intents.current_factory()() as session:
        try:
            yield session
        finally:
            await session.rollback()


async def get_collection(
    tenant_id: str, collection_id: uuid.UUID, principal: ResourcePrincipal, *, db: Any = None
) -> CollectionRead | None:
    """The collection if *principal* may view it in *tenant_id*, else ``None``."""
    with tenant_scope(tenant_id):
        async with _session(db) as session:
            stmt = POLICY.filter(
                principal, ACTION_VIEW, select(Collection).where(Collection.id == collection_id)
            )
            row = (await session.execute(stmt)).scalars().first()
            return None if row is None else CollectionRead.from_row(row)


async def list_collections(
    tenant_id: str,
    principal: ResourcePrincipal,
    *,
    filter: str = "all",
    limit: int = constants.PAGE_DEFAULT,
    cursor: str | None = None,
    db: Any = None,
) -> CollectionPageRead:
    """One page of what *principal* may view in *tenant_id*, newest first.

    ``filter`` is the API's (``owned|shared|internal|public|all``); ``limit`` is
    clamped to ``1..PAGE_MAX``. Follow ``next_cursor`` for the rest.
    """
    limit = max(1, min(limit, constants.PAGE_MAX))
    with tenant_scope(tenant_id):
        async with _session(db) as session:
            rows, token, total = await service.list_page(
                session, principal, filter_=filter, limit=limit, cursor=cursor
            )
            return CollectionPageRead(
                items=[CollectionRead.from_row(r) for r in rows], next_cursor=token, total=total
            )


def rendition_url(image: Any, size: str, *, collection: Any = None) -> str:
    """The URL that streams *image*'s rendition *size* (:func:`sm_images.urls.rendition_url`).

    Access is checked by the route, not here: a URL for an image the viewer may
    not open is a 404 when followed. ``?v=`` is the image's display generation,
    so a regenerated rendition is never served from a stale cache. Pass the
    image's *collection* to let a public one go through ``public_asset_base_url``.
    """
    return urls.rendition_url(image, size, collection=collection)
