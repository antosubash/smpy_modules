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

from sm_records.endpoints.api import records, referrers, revisions, types

router = APIRouter()
router.include_router(types.router)
router.include_router(records.router)
router.include_router(referrers.router)
router.include_router(revisions.router)

__all__ = ["router"]
