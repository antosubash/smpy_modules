"""JSON API for the Images module, mounted under ``ROUTE_PREFIX_API``.

``router`` is what :meth:`ImagesModule.register_routes` includes; the
per-resource routers are added to it here as they land.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from simple_module_hosting.csrf import RequiresCsrf

from sm_images.endpoints.api import collections, images, shares, uploads
from sm_images.tenancy import bind_admin

# The tenant binding is the router's **first** dependency, and FastAPI puts a
# parent router's dependencies ahead of every included route's, so it is first
# for every route below. Not cosmetic: yield dependencies exit in reverse, and
# ``get_db`` - opened by the permission check - commits on its way out, which
# has to happen while the tenant is still bound.
#
# Then the framework's CSRF check on every write: the session cookie's
# SameSite=Lax does not separate the console from an organisation's public
# site, which is same-site with it. Reads pass. Anonymous routes are mounted on
# their own router and never carry either.
router = APIRouter(dependencies=[Depends(bind_admin), Depends(RequiresCsrf())])
router.include_router(collections.router)
router.include_router(shares.router)
router.include_router(images.router)
router.include_router(uploads.router)
