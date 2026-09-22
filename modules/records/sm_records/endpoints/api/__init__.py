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

from sm_records.endpoints.api import (
    aggregate,
    io,
    io_types,
    lifecycle,
    preview,
    records,
    referrers,
    revisions,
    translations,
    types,
)

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
# Beside ``io``: the type-definition half of import/export, split off for
# the file cap. Its paths (``/types/import``, ``/types/{key}/export``) are
# distinct from every other router's, so its position is not load-bearing.
router.include_router(io_types.router)
# Before ``records`` for the reason ``io`` is: ``/types/{key}/records/{uuid}``
# would otherwise match ``/types/{key}/records/aggregate`` as a record whose
# uuid is "aggregate".
router.include_router(aggregate.router)
# Before ``records`` for the same reason ``io`` is: both add paths under
# ``/types/{key}/records/{uuid}/…``, and registration order is what Starlette
# matches in.
router.include_router(translations.router)
# Before ``records`` for the same reason, and it is the same resource seen
# from the other side: ``/types/{key}/records/{uuid}/restore`` and
# ``…/purge`` sit under the path ``records`` claims for one record.
router.include_router(lifecycle.router)
router.include_router(records.router)
router.include_router(referrers.router)
router.include_router(revisions.router)

__all__ = ["router"]
