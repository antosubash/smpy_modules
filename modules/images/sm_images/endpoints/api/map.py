"""``GET /collections/{id}/points`` and ``GET|HEAD …/map.pmtiles`` (spec §5).

``CollectionView`` re-reads the collection through the policy on every request
- every range request of a map viewer included - so a collection the caller
may no longer see is the 404 an unknown id gets. The anonymous twins are in
:mod:`sm_images.endpoints.public`. Both answers depend on who asks, so both
are ``private``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from simple_module_core.resources import ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import resource_principal

from sm_images import serving
from sm_images.access import CollectionView, can_edit
from sm_images.endpoints.deps import require_view
from sm_images.endpoints.map_params import BBox, Cursor, Limit, get_and_head, points_response
from sm_images.map.schedule import rebuild_pending

Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]
router = APIRouter(prefix="/collections", tags=["images-map"])


@router.get("/{collection_id}/points", dependencies=[require_view])
async def collection_points(
    request: Request,
    response: Response,
    collection: CollectionView,
    db: Any = Depends(get_db),
    bbox: str | None = BBox,
    limit: int = Limit,
    cursor: str | None = Cursor,
) -> dict[str, Any]:
    """GeoJSON points of the collection: ``id``, ``captured_at``, ``group_id``."""
    return await points_response(
        request, response, db, collection, bbox=bbox, limit=limit, cursor=cursor, twin=False
    )


async def collection_map(
    request: Request, collection: CollectionView, who: Principal, db: Any = Depends(get_db)
) -> Response:
    """The collection's PMTiles archive, with ``Range``; ``X-Map-Stale: 1`` for
    an editor while a rebuild is pending (they see every point anyway)."""

    async def stale() -> bool:
        return rebuild_pending(collection) and await can_edit(db, who, collection)

    return await serving.serve_map(request, collection, twin=False, stale=stale)


_MAP = "/{collection_id}/map.pmtiles"
get_and_head(router, _MAP, dependencies=[require_view])(collection_map)
