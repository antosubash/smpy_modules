"""Everything events serves to an anonymous visitor.

**One router per content locale.** The default language keeps the bare prefix
(``/events/...``) and every other is prefixed with its tag (``/de/events/...``), as news
and pagebuilder address theirs. A router each rather than a ``/{locale}`` path parameter:
a parameter matches *any* first segment, and the public-route registry exempts by string
prefix. Mounted from ``on_startup`` (:mod:`sm_events.core.boot`), because the prefix and
the languages come from the database.

**Registration order inside one is load-bearing.** FastAPI matches routes in the order they
are added and ``/{slug}`` matches any single segment, so every fixed path goes before it,
in this order:

1. ``GET|HEAD /sitemap.xml`` (default language only)
2. ``/api/occurrences`` (default language only)
3. ``/calendar.ics``, ``/c/{calendar}.ics``
4. ``/c/{calendar}``, ``/``
5. ``/{slug}.ics``
6. ``/{slug}`` last

(``calendar``, ``c``, ``api``, ``feed`` and ``sitemap`` are reserved slugs for this reason.)
The bare prefix (``/events``) is the redirect Starlette makes to ``/events/``; the auth
exemption covers both.

**Two binders.** The pages a person reads bind with
:func:`~sm_events.web.endpoints.public._tenant.public_tenant`, which yields ``None`` for a
request that resolved no tenant so the endpoint answers the 404 without a query. The
machine-read routes (feeds, sitemap, API) bind with ``bind_public``: no tenant is a plain
404. Both are the router's **first** dependency. Every router uses
:class:`~sm_events.web.endpoints.public._errors.PublicErrorRoute`, so every error leaves
``no-store``.

Nothing here takes a viewer from the request: the anonymous gate
(:mod:`sm_events.core.access.public`) decides what is visible, for everyone.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from simple_module_db.deps import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from sm_events.core import constants, locales
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import bind_public
from sm_events.web.endpoints.deps import get_settings
from sm_events.web.endpoints.public._api import api_router
from sm_events.web.endpoints.public._cache import permanent_redirect
from sm_events.web.endpoints.public._errors import PublicErrorRoute
from sm_events.web.endpoints.public._event import event_router
from sm_events.web.endpoints.public._feeds import calendar_feed_router, event_feed_router
from sm_events.web.endpoints.public._index import index_router
from sm_events.web.endpoints.public._not_found import not_found
from sm_events.web.endpoints.public._sitemap import sitemap_router
from sm_events.web.endpoints.public._tenant import public_tenant

__all__ = ["alias_router", "public_router"]


def public_router(locale: str) -> APIRouter:
    """Everything one language serves, ready to mount under its own prefix."""
    router = APIRouter()
    machine = [Depends(bind_public)]
    reader = [Depends(public_tenant)]
    if locales.is_default(locale):
        router.include_router(sitemap_router(), dependencies=machine)
        router.include_router(api_router(), dependencies=machine)
    router.include_router(calendar_feed_router(locale), dependencies=machine)
    router.include_router(index_router(locale), dependencies=reader)
    router.include_router(event_feed_router(locale), dependencies=machine)
    router.include_router(event_router(locale), dependencies=reader)
    return router


def alias_router(prefix: str) -> APIRouter:
    """``/{default}{prefix}/...`` to ``{prefix}/...``, permanently, query string kept.

    The default language serves unprefixed, but anything that builds URLs by pasting a locale
    in front asks for the redundant form; serving it would put one document at two addresses.
    Bound like every public router: a request that resolved no tenant gets the 404, not a 301.
    """
    router = APIRouter(route_class=PublicErrorRoute, dependencies=[Depends(public_tenant)])

    @router.api_route("/{rest:path}", methods=sorted(constants.PUBLIC_METHODS), response_model=None)
    async def redirect_to_unprefixed(
        rest: str,
        request: Request,
        inertia: InertiaDep,
        db: AsyncSession = Depends(get_db),
        tenant: str | None = Depends(public_tenant),
        settings: EventsSettings = Depends(get_settings),
    ) -> Response:
        if tenant is None:
            return await not_found(request, inertia, db, locale=locales.default(), tenant=None)
        target = f"{prefix}/{rest}"
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return permanent_redirect(request, settings, target)

    return router
