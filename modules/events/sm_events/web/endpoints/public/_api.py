"""``/api/occurrences``: the public occurrences read for the read-only grid.

Machine-read, on the default language's prefix only. Answers the 404 until it lands; the
path is final.
"""

from __future__ import annotations

from fastapi import APIRouter

from sm_events.core import constants
from sm_events.core.errors import NotFound
from sm_events.web.endpoints.public._errors import PublicErrorRoute

__all__ = ["api_router"]


def api_router() -> APIRouter:
    router = APIRouter(route_class=PublicErrorRoute)

    @router.api_route(
        f"/{constants.SEGMENT_API}/occurrences", methods=sorted(constants.PUBLIC_METHODS)
    )
    async def public_occurrences() -> None:
        raise NotFound

    return router
