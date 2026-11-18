"""The ``.ics`` routes: every public calendar's feed, one calendar's, one event's.

Machine-read: a request that resolved no tenant is a plain 404 with the
``{"detail", "code"}`` envelope. They answer that 404 until the feeds land; the paths and
the router order are final (``/calendar.ics`` before ``/{slug}.ics``).
"""

from __future__ import annotations

from fastapi import APIRouter

from sm_events.core import constants
from sm_events.core.errors import NotFound
from sm_events.web.endpoints.public._errors import PublicErrorRoute

__all__ = ["calendar_feed_router", "event_feed_router"]

_METHODS = sorted(constants.PUBLIC_METHODS)


def calendar_feed_router(locale: str) -> APIRouter:
    router = APIRouter(route_class=PublicErrorRoute)

    @router.api_route(f"/{constants.SEGMENT_CALENDAR_FEED}.ics", methods=_METHODS)
    async def all_calendars_feed() -> None:
        raise NotFound

    @router.api_route(f"/{constants.SEGMENT_CALENDAR}/{{calendar}}.ics", methods=_METHODS)
    async def calendar_feed(calendar: str) -> None:
        raise NotFound

    return router


def event_feed_router(locale: str) -> APIRouter:
    router = APIRouter(route_class=PublicErrorRoute)

    @router.api_route("/{slug}.ics", methods=_METHODS)
    async def event_ics(slug: str) -> None:
        raise NotFound

    return router
