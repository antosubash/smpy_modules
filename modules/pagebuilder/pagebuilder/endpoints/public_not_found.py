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
from simple_module_hosting._error_handlers import _wants_json as _framework_wants_json
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
    """Whether this caller gets the JSON body rather than the page.

    Exactly the framework's own error-page negotiation, so one request never
    sees two error shapes depending on who answered it: an Inertia visit
    always gets the page, q-values are honoured (``text/html;q=0`` rules the
    page out; ``application/json, text/html;q=0.5`` prefers JSON), and a
    browser navigation gets the page. It is a private helper of the
    framework's, imported rather than copied so the two cannot drift; the
    framework range (``<0.1``) bounds the exposure, and a test pins the
    behaviour.
    """
    return _framework_wants_json(request)


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
