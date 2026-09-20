"""JSON API for the Records module, mounted under ``ROUTE_PREFIX_API``.

``router`` is what :meth:`RecordsModule.register_routes` includes. The
per-resource routers are added to it here as they land, so the host boots at
every intermediate commit.

``public`` is **not** among them: the anonymous read API is mounted at its own
configurable prefix from ``on_startup`` (:mod:`sm_records.boot`), because the
prefix is a database-backed setting the host has not hydrated yet at the point
this router is built.
"""

from __future__ import annotations

from fastapi import APIRouter

from sm_records.endpoints.api import io, preview, records, referrers, revisions, types

router = APIRouter()
# Before ``types``: ``/types/{key}/schema/preview/{job}`` is a GET the types
# router has no route for, but keeping the pair adjacent is what makes the
# split between them visible at the mount point.
router.include_router(preview.router)
router.include_router(types.router)
# Before ``records``: Starlette matches in registration order, and
# ``/types/{key}/records/{uuid}`` would otherwise swallow
# ``/types/{key}/records/export`` as a record whose uuid is "export".
router.include_router(io.router)
router.include_router(records.router)
router.include_router(referrers.router)
router.include_router(revisions.router)

__all__ = ["router"]
