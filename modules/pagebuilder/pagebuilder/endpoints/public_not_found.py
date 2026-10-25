"""The public viewer's answer for a page a visitor cannot see (#89).

One answer for every cause — an unknown slug, a draft, a trashed page, one
scheduled but not yet live, a request that resolved no tenant — so the body
says nothing about which applied: it is no oracle for which drafts exist, the
same rule the tenancy 404 follows.

Rendered as the module's own ``PublicNotFound`` page inside the site's frame
(header, footer, branding, design pack) rather than raised to the host's
generic error page, which knows nothing of the site and is whatever the host
happens to ship.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder import public_cache, site_nav
from pagebuilder.html_lang import set_html_lang
from pagebuilder.layout_service import LayoutService, public_layout_props
from pagebuilder.public_copy import public_copy
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.site_nav import SiteNav
from pagebuilder.tenancy import vary_on_tenant

PAGE_NOT_FOUND: Final = "PageBuilder/PublicNotFound"
NOT_FOUND_DETAIL: Final = "Page not found"
"""The JSON body's detail, word for word what the viewer raised before."""

NO_STORE: Final = "no-store"
"""Never kept anywhere. A shared cache holding one tenant's 404 could answer
another tenant's address with it, and a page published a second later must not
be hidden behind a cached "missing"."""


def _accept_q(accept: str, media_type: str) -> float | None:
    """The q-value ``accept`` gives ``media_type`` by name, or ``None`` when it
    is not listed. Wildcards don't count: what matters is whether the caller
    *named* the type. A malformed q is 1.0 (RFC 9110)."""
    for part in accept.split(","):
        media, _, params = part.partition(";")
        if media.strip().lower() != media_type:
            continue
        q = 1.0
        for param in params.split(";"):
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    q = float(value.strip())
                except ValueError:
                    q = 1.0
        return q
    return None


def wants_json(request: Request) -> bool:
    """Whether this caller gets the JSON body rather than the page.

    The same answer the framework's error pages give on a non-API path, so one
    request never sees two error shapes depending on who answered it. Kept
    local because the framework's helper is private and has already moved
    once:

    - an Inertia visit always gets the page, whatever its ``Accept``;
    - HTML named with q > 0, at least as preferred as JSON → the page;
    - HTML refused (``q=0``) → JSON, if JSON was named at all;
    - otherwise JSON only when it was named with q > 0 (``*/*`` → the page).
    """
    if request.headers.get("x-inertia"):
        return False
    accept = request.headers.get("accept", "")
    html_q = _accept_q(accept, "text/html")
    json_q = _accept_q(accept, "application/json")
    if html_q is not None and html_q > 0 and html_q >= (json_q or 0.0):
        return False
    if html_q == 0:
        return json_q is not None
    return bool(json_q)


async def render_not_found(
    request: Request,
    inertia: InertiaDep,
    settings: PagebuilderSettings,
    *,
    locale: str,
    db: AsyncSession | None,
) -> Response:
    """The 404, in ``locale``, framed by the tenant's layout when there is one.

    ``db`` is ``None`` for a request that resolved no tenant: the page then
    renders with the default branding and no header or footer, never another
    site's. The layout and nav are read only when the page is rendered, so a
    JSON caller costs no queries.
    """
    response: Response
    if wants_json(request):
        response = JSONResponse({"detail": NOT_FOUND_DETAIL}, status_code=404)
    else:
        frame: dict[str, Any] = {"layout_header": None, "layout_footer": None}
        nav: SiteNav | None = None
        if db is not None:
            frame = public_layout_props(await LayoutService(db).get())
            nav = await site_nav.site_nav(db, settings.public_route_prefix, locale)
        response = await inertia.render(
            PAGE_NOT_FOUND,
            {
                "locale": locale,
                # The site root. A prefixed locale has no root of its own
                # (`/de/` is not a route), so every language links to `/`.
                "home_href": "/",
                "site_name": settings.site_name,
                "copy": public_copy(locale),
                **frame,
                "site_nav": nav,
            },
        )
        response.status_code = 404
        if not request.headers.get("x-inertia"):
            set_html_lang(response, locale)
    response.headers["Cache-Control"] = NO_STORE
    response.headers["Vary"] = public_cache.VARY
    response.headers["Content-Language"] = locale
    vary_on_tenant(response, request)
    if settings.public_csp:
        response.headers["Content-Security-Policy"] = settings.public_csp
    return response
