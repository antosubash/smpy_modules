"""One event's page (``/{slug}``), registered after every fixed path.

Answers the 404 until the page lands; the path and the router order are final.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from simple_module_db.deps import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from sm_events.core import constants
from sm_events.web.endpoints.public._errors import PublicErrorRoute
from sm_events.web.endpoints.public._not_found import not_found
from sm_events.web.endpoints.public._tenant import public_tenant

__all__ = ["event_router"]

_METHODS = sorted(constants.PUBLIC_METHODS)


def event_router(locale: str) -> APIRouter:
    router = APIRouter(route_class=PublicErrorRoute)

    @router.api_route("/{slug}", methods=_METHODS, response_model=None)
    async def event_page(
        slug: str,
        request: Request,
        inertia: InertiaDep,
        db: AsyncSession = Depends(get_db),
        tenant: str | None = Depends(public_tenant),
    ) -> Response:
        return await not_found(request, inertia, db, locale=locale, tenant=tenant)

    return router
