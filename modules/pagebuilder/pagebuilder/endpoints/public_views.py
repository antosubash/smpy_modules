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


def _etag_for(
    page_id: int,
    updated_at: datetime | None,
    layout_updated_at: datetime | None = None,
) -> str:
    """Stable, short ETag derived from page identity + last-modified time.

    ``layout_updated_at`` participates so a site-wide header / footer
    edit invalidates every page's cached chrome — without it, clients
    keep serving stale layout from cache until the page itself changes.
    """
    stamp = updated_at.isoformat() if updated_at is not None else ""
    layout_stamp = (
        layout_updated_at.isoformat() if layout_updated_at is not None else ""
    )
    digest = hashlib.sha1(f"{page_id}:{stamp}:{layout_stamp}".encode()).hexdigest()[:16]
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
    etag = _etag_for(page.id or 0, page.updated_at, layout.updated_at)
    cache_parts = [f"max-age={settings.public_cache_max_age}"]
    if settings.public_cache_swr > 0:
        cache_parts.append(f"stale-while-revalidate={settings.public_cache_swr}")
    cache_control = "public, " + ", ".join(cache_parts)

    def apply_headers(response: Response) -> Response:
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = cache_control
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
