"""``/sitemap.xml``: every public event, on the default language's prefix only.

Machine-read. Answers the 404 until the sitemap lands; the path is final.
"""

from __future__ import annotations

from fastapi import APIRouter

from sm_events.core import constants
from sm_events.core.errors import NotFound
from sm_events.web.endpoints.public._errors import PublicErrorRoute

__all__ = ["sitemap_router"]


def sitemap_router() -> APIRouter:
    router = APIRouter(route_class=PublicErrorRoute)

    @router.api_route(f"/{constants.SEGMENT_SITEMAP}.xml", methods=sorted(constants.PUBLIC_METHODS))
    async def sitemap() -> None:
        raise NotFound

    return router
