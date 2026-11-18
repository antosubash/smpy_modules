"""The upcoming list and one public calendar's page (``/`` and ``/c/{calendar}``).

Answers the 404 until the pages land; the paths and the router order are final.
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

__all__ = ["index_router"]

_METHODS = sorted(constants.PUBLIC_METHODS)


def index_router(locale: str) -> APIRouter:
    router = APIRouter(route_class=PublicErrorRoute)

    @router.api_route(
        f"/{constants.SEGMENT_CALENDAR}/{{calendar}}", methods=_METHODS, response_model=None
    )
    async def calendar_page(
        calendar: str,
        request: Request,
        inertia: InertiaDep,
        db: AsyncSession = Depends(get_db),
        tenant: str | None = Depends(public_tenant),
    ) -> Response:
        return await not_found(request, inertia, db, locale=locale, tenant=tenant)

    @router.api_route("/", methods=_METHODS, response_model=None)
    async def index_page(
        request: Request,
        inertia: InertiaDep,
        db: AsyncSession = Depends(get_db),
        tenant: str | None = Depends(public_tenant),
    ) -> Response:
        return await not_found(request, inertia, db, locale=locale, tenant=tenant)

    return router
