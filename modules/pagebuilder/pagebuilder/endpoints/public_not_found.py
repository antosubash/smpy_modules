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

from typing import Final

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from simple_module_hosting.inertia_deps import InertiaDep

from pagebuilder import public_cache
from pagebuilder.html_lang import set_html_lang
from pagebuilder.layout_service import public_layout_props
from pagebuilder.models import Layout
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


def wants_json(request: Request) -> bool:
    """An API-shaped caller that named JSON and not HTML.

    The framework's negotiation in miniature: an Inertia visit always gets the
    page component, and a browser navigation names ``text/html``.
    """
    if request.headers.get("x-inertia"):
        return False
    accept = request.headers.get("accept", "").lower()
    return "application/json" in accept and "text/html" not in accept


async def render_not_found(
    request: Request,
    inertia: InertiaDep,
    settings: PagebuilderSettings,
    *,
    locale: str,
    layout: Layout | None,
    nav: SiteNav | None,
) -> Response:
    """The 404, in ``locale``, framed by ``layout`` when there is a tenant.

    ``layout`` and ``nav`` are ``None`` for a request that resolved no tenant:
    the page then renders with the default branding and no header or footer,
    never another site's.
    """
    response: Response
    if wants_json(request):
        response = JSONResponse({"detail": NOT_FOUND_DETAIL}, status_code=404)
    else:
        frame = (
            public_layout_props(layout)
            if layout is not None
            else {"layout_header": None, "layout_footer": None}
        )
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
