"""JSON API for the Records module, mounted under ``ROUTE_PREFIX_API``.

``router`` is what :meth:`RecordsModule.register_routes` includes. The
per-resource routers (types, records, public) are added to it here as they
land, so the host boots at every intermediate commit.
"""

from __future__ import annotations

from fastapi import APIRouter

from sm_records.endpoints.api import records, types

router = APIRouter()
router.include_router(types.router)
router.include_router(records.router)

__all__ = ["router"]
