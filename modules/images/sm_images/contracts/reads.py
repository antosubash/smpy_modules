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
from sm_images.map import points as map_points
from sm_images.models import Collection
from sm_images.services import collections as service
from sm_images.tenancy import tenant_scope

__all__ = ["get_collection", "list_collections", "points", "rendition_url"]


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


async def points(
    tenant_id: str,
    collection_id: uuid.UUID,
    principal: ResourcePrincipal,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    limit: int = constants.POINTS_LIMIT_DEFAULT,
    cursor: str | None = None,
    db: Any = None,
) -> dict[str, Any] | None:
    """The collection's map points as a GeoJSON ``FeatureCollection`` (what
    ``GET …/collections/{id}/points`` answers), or ``None`` when *principal*
    may not view it in *tenant_id*.

    Each point carries ``id``, ``captured_at`` and ``group_id`` only; an image
    whose picture may not be shown yet (redaction pending) is not a point.
    ``bbox`` is ``(minx, miny, maxx, maxy)`` in degrees (``minx > maxx``
    crosses the antimeridian; out of range raises ``Invalid``); ``limit`` is
    clamped to ``POINTS_LIMIT_MAX``. Follow ``next_cursor`` for the rest.
    """
    box = None if bbox is None else map_points.check_bbox(tuple(bbox))
    with tenant_scope(tenant_id):
        async with _session(db) as session:
            stmt = POLICY.filter(
                principal, ACTION_VIEW, select(Collection).where(Collection.id == collection_id)
            )
            row = (await session.execute(stmt)).scalars().first()
            if row is None:
                return None
            return await map_points.page(session, row, bbox=box, limit=limit, cursor=cursor)


def rendition_url(image: Any, rendition: Any, *, collection: Any = None) -> str:
    """The URL that streams *rendition* (one of *image*'s ``Rendition`` rows);
    see :func:`sm_images.urls.rendition_url`.

    Access is checked by the route, not here: a URL for an image the viewer may
    not open is a 404 when followed. ``?v=`` names the rendition's own bytes
    (its source generation and key), so a regenerated rendition is a new URL.
    Pass the image's *collection* to let a public one go through
    ``public_asset_base_url``.
    """
    return urls.rendition_url(image, rendition, collection=collection)
