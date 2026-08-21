"""The public page viewer.

Split from the admin views because it is the one route in this module that
serves anonymous visitors: it carries the ETag, cache, CSP, canonical and
old-slug redirect handling, none of which an admin screen has any use for.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder import redirects
from pagebuilder.deps import get_settings
from pagebuilder.layout_service import LayoutService, public_layout_props
from pagebuilder.service import PagesService
from pagebuilder.settings import PagebuilderSettings

public_router = APIRouter()

_PAGE_PUBLIC = "PageBuilder/PublicPage"


#: The two things this route can return. Different bytes, different content
#: types — so under RFC 9110 they are different representations and must not
#: share a validator.
_DOCUMENT = "doc"
_INERTIA = "inertia"


def _representation_of(request: Request) -> str:
    """Which of the two this request is asking for.

    Mirrors ``Inertia._is_inertia_request`` (presence of the header, not its
    value) on purpose: that check is what actually decides, inside
    ``inertia.render()``, whether this request gets JSON or HTML back. Matching
    on ``== "true"`` instead would disagree with it for any non-empty value
    other than the literal string ``"true"`` (e.g. a client or proxy that
    sends ``X-Inertia: 1``) -- the route would then cache the JSON payload,
    auth block included, under the *document*'s public, shared validator.
    That is the same crossover this module exists to close, just gated on
    header value instead of header presence.
    """
    return _INERTIA if "x-inertia" in request.headers else _DOCUMENT


def _etag_for(
    page_id: int,
    updated_at: datetime | None,
    layout_updated_at: datetime | None = None,
    representation: str = _DOCUMENT,
) -> str:
    """Stable, short ETag derived from page identity + last-modified time.

    ``layout_updated_at`` participates so a site-wide header / footer
    edit invalidates every page's cached chrome — without it, clients
    keep serving stale layout from cache until the page itself changes.

    ``representation`` participates because this route answers the same URL
    with an HTML document or an Inertia JSON payload, depending on the
    request's ``X-Inertia`` header. One validator across both let a client
    holding the payload revalidate a *document* request into a 304 and carry
    on rendering JSON as the page — which is what visitors hit on a live site
    after following a link to a page and then opening its URL directly.
    Including it also retires every ETag issued before this fix, so a cache
    already holding the wrong representation heals on its next revalidation
    instead of having it confirmed for another cycle.
    """
    stamp = updated_at.isoformat() if updated_at is not None else ""
    layout_stamp = (
        layout_updated_at.isoformat() if layout_updated_at is not None else ""
    )
    seed = f"{page_id}:{stamp}:{layout_stamp}:{representation}"
    digest = hashlib.sha1(seed.encode()).hexdigest()[:16]
    return f'W/"{digest}"'


def _public_base_url(request: Request, settings: PagebuilderSettings) -> str:
    """Resolve the public origin used to build absolute URLs.

    Prefer the explicit setting (the deployment knows its public host)
    and only fall back to the inbound request for local dev / scenarios
    where the host header is trustworthy. Always returned without a
    trailing slash so callers can concatenate path segments directly.
    """
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    return f"{request.url.scheme}://{request.url.netloc}".rstrip("/")


def _absolute_page_url(
    request: Request, settings: PagebuilderSettings, slug: str
) -> str:
    base = _public_base_url(request, settings)
    prefix = settings.public_route_prefix.rstrip("/")
    return f"{base}{prefix}/{slug}"



@public_router.get("/{slug}", response_model=None)
async def public_view(
    slug: str,
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
    settings: PagebuilderSettings = Depends(get_settings),
) -> Response:
    page = await PagesService(db).get_by_slug_published(slug)
    if page is None or page.published_data is None:
        # Before giving up: this may be an address the page used to live at.
        moved = await redirects.response_for(db, slug, prefix=settings.public_route_prefix)
        if moved is not None:
            return moved
        raise HTTPException(status_code=404, detail="Page not found")

    layout = await LayoutService(db).get()
    representation = _representation_of(request)
    etag = _etag_for(page.id or 0, page.updated_at, layout.updated_at, representation)
    # The page body is the same for every visitor, but the Inertia payload
    # wrapped around it is not: the framework merges the signed-in user's auth
    # block, permissions and menus into it. Only the document is public.
    if representation == _INERTIA:
        cache_control = "private, no-store"
    else:
        cache_parts = [f"max-age={settings.public_cache_max_age}"]
        if settings.public_cache_swr > 0:
            cache_parts.append(f"stale-while-revalidate={settings.public_cache_swr}")
        cache_control = "public, " + ", ".join(cache_parts)

    def apply_headers(response: Response) -> Response:
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = cache_control
        # Merged into the existing value rather than appended as a second
        # `Vary` line: the Inertia render already set `Vary: Accept`, and
        # `add_vary_header` is what every middleware downstream uses. One of
        # those reading `vary`, extending it and assigning it back would drop
        # a separate line — SessionMiddleware adding `Cookie` does exactly
        # that, and silently took `X-Inertia` with it.
        response.headers.add_vary_header("X-Inertia")
        if settings.public_csp:
            response.headers["Content-Security-Policy"] = settings.public_csp
        return response

    if request.headers.get("if-none-match") == etag:
        return apply_headers(Response(status_code=304))

    canonical = page.canonical_url or _absolute_page_url(request, settings, slug)
    return apply_headers(
        await inertia.render(
            _PAGE_PUBLIC,
            {
                "title": page.title,
                "data": page.published_data,
                "meta_description": page.meta_description,
                "og_image": page.og_image,
                "canonical_url": canonical,
                "og_url": canonical,
                "index_in_search": page.index_in_search,
                "json_ld": page.json_ld,
                "site_name": settings.site_name,
                "twitter_handle": settings.twitter_handle,
                **public_layout_props(layout),
            },
        )
    )
