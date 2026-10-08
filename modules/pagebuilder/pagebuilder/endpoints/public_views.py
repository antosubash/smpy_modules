"""The public page viewer.

Split from the admin views because it is the one route in this module that
serves anonymous visitors: it carries the ETag, cache, CSP, canonical,
``hreflang`` and old-slug redirect handling, none of which an admin screen has
any use for.

One router, mounted once per content locale — see
:meth:`pagebuilder.module.PagebuilderModule.on_startup`. The default language
keeps the bare prefix (``/p/{slug}``) and every other one is prefixed
(``/de/p/{slug}``), which is what lets a site add a second language without
rewriting an address that already exists.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder import locales, public_claims, redirects
from pagebuilder.deps import get_settings
from pagebuilder.layout_service import LayoutService, public_layout_props
from pagebuilder.service import PagesService
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.tenancy import bind_public, vary_on_tenant

_PAGE_PUBLIC = "PageBuilder/PublicPage"


def _etag_for(
    page_id: int,
    updated_at: datetime | None,
    layout_updated_at: datetime | None = None,
    variant: str = "html",
) -> str:
    """Stable, short ETag derived from page identity + last-modified time.

    ``layout_updated_at`` participates so a site-wide header / footer
    edit invalidates every page's cached chrome — without it, clients
    keep serving stale layout from cache until the page itself changes.

    The locale needs no place in the digest: a page belongs to exactly one
    language, so ``page_id`` already names it.

    ``variant`` names the representation ("html" or "inertia"): one URL answers
    with a full page or Inertia's JSON, and a shared tag lets a browser holding
    the page get a 304 for the JSON request and hand Inertia cached HTML.
    """
    stamp = updated_at.isoformat() if updated_at is not None else ""
    layout_stamp = (
        layout_updated_at.isoformat() if layout_updated_at is not None else ""
    )
    digest = hashlib.sha1(f"{page_id}:{stamp}:{layout_stamp}:{variant}".encode()).hexdigest()[:16]
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
    request: Request, settings: PagebuilderSettings, slug: str, prefix: str, locale: str
) -> str:
    base = _public_base_url(request, settings)
    return f"{base}{locales.public_path(prefix, slug, locale)}"


async def _alternates(
    db: AsyncSession,
    request: Request,
    settings: PagebuilderSettings,
    group: str,
) -> list[dict[str, str]]:
    """``hreflang`` entries for every *published* page in the group.

    Only published ones: advertising a draft translation points a crawler at a
    404 and offers a reader a language switch that dead-ends.

    Each sibling is resolved through :mod:`pagebuilder.public_claims`, exactly
    as the sitemap does, rather than assembled from the *caller's* prefix: a
    translation group can hold a page this module serves and one another
    module has claimed — translate an article's page from the page list and it
    does — and pasting one prefix over both would advertise ``/de/news/x`` for
    an ordinary page or ``/p/x`` for an article. Both 404, in the one place a
    404 is invisible until traffic drops.

    Omitted entirely when the group has one member, which is every page on a
    monolingual site — a lone ``hreflang`` pointing at the page itself says
    nothing and is noise in the head of every document.
    """
    published = await PagesService(db).published_alternates(group)
    if len(published) < 2:
        return []
    base = _public_base_url(request, settings)
    alternates = []
    for locale, slug in published:
        claimed = await public_claims.claimed_url(db, slug, locale)
        alternates.append(
            {
                "locale": locale,
                "url": f"{base}{claimed}"
                if claimed
                else _absolute_page_url(
                    request, settings, slug, settings.public_route_prefix, locale
                ),
            }
        )
    # x-default names the version to serve someone whose language nobody
    # matched. The site's own default is the only defensible answer.
    default = next(
        (alt for alt in alternates if locales.is_default(alt["locale"])), None
    )
    if default is not None:
        alternates.append({"locale": "x-default", "url": default["url"]})
    return alternates


async def render_public_page(
    slug: str,
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession,
    settings: PagebuilderSettings,
    *,
    url_prefix: str | None = None,
    locale: str | None = None,
) -> Response:
    """Serve a published page, with everything a public URL needs.

    Exposed rather than kept inside the route so a module that claims a page's
    public address (see :mod:`pagebuilder.public_claims`) serves it through the
    same ETag, cache, CSP, canonical, ``hreflang`` and old-slug handling instead
    of growing a second viewer that drifts from this one.

    ``url_prefix`` is the address the caller serves at, used for the canonical
    URL and for old-slug redirects. It defaults to this module's own, which is
    what the route below passes. ``locale`` is which language's page to look
    for — the default one when the caller does not say, so a monolingual host
    and every pre-existing caller behave exactly as before.
    """
    prefix = url_prefix if url_prefix is not None else settings.public_route_prefix
    active = locale or locales.default()
    page = await PagesService(db).get_by_slug_published(slug, active)
    if page is None or page.published_data is None:
        # Before giving up: this may be an address the page used to live at.
        moved_to = await redirects.resolve(db, slug, active)
        if moved_to is not None:
            # The page's current address, wherever that now is. When another
            # module has claimed it, the old URL forwards *there* rather than
            # to this module's version of it — that one 404s, and sending a
            # visitor to it would turn a rename into a broken link, which is
            # the exact thing recording a redirect exists to prevent.
            claimed = await public_claims.claimed_url(db, moved_to, active)
            target = claimed or locales.public_path(prefix, moved_to, active)
            # A 301 is cacheable by default; key it on what picks the tenant.
            return vary_on_tenant(RedirectResponse(target, status_code=301), request.app)
        raise HTTPException(status_code=404, detail="Page not found")

    layout = await LayoutService(db).get()
    variant = "inertia" if request.headers.get("x-inertia") else "html"
    etag = _etag_for(page.id or 0, page.updated_at, layout.updated_at, variant)
    cache_parts = [f"max-age={settings.public_cache_max_age}"]
    if settings.public_cache_swr > 0:
        cache_parts.append(f"stale-while-revalidate={settings.public_cache_swr}")
    cache_control = "public, " + ", ".join(cache_parts)

    def apply_headers(response: Response) -> Response:
        response.headers["ETag"] = etag
        response.headers["Vary"] = "X-Inertia"
        # On a multi-tenant host the tenant can come from the session, not the Host.
        vary_on_tenant(response, request.app)
        response.headers["Cache-Control"] = cache_control
        # Which language was negotiated, for caches and for anything reading
        # the response without parsing the body.
        response.headers["Content-Language"] = page.locale
        if settings.public_csp:
            response.headers["Content-Security-Policy"] = settings.public_csp
        return response

    if request.headers.get("if-none-match") == etag:
        return apply_headers(Response(status_code=304))

    canonical = page.canonical_url or _absolute_page_url(
        request, settings, slug, prefix, page.locale
    )
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
                "locale": page.locale,
                "alternates": await _alternates(
                    db, request, settings, page.translation_group
                ),
                **public_layout_props(layout),
            },
        )
    )


def locale_router(locale: str) -> APIRouter:
    """A viewer bound to one language.

    One router per content locale rather than a ``/{locale}`` path parameter,
    because a parameter would match *any* first segment: ``/xx/p/about`` would
    reach the handler and have to be rejected there, and — worse — the public
    route registry exempts by string prefix, so the exemption would have to be
    widened to something that no longer describes what is public.

    ``bind_public`` comes first so everything the viewer reads — redirects,
    claims, layout, alternates — runs in the request's tenant, and a request
    that resolved none gets the unknown-slug 404.
    """
    router = APIRouter(dependencies=[Depends(bind_public)])

    @router.get("/{slug}", response_model=None)
    async def public_view(
        slug: str,
        request: Request,
        inertia: InertiaDep,
        db: AsyncSession = Depends(get_db),
        settings: PagebuilderSettings = Depends(get_settings),
    ) -> Response:
        """A published page at this module's own address, in one language.

        A slug another module has claimed is *not* served here, even though the
        page exists and is published: it answers at the claimant's address
        instead, and serving it at both would put the same document at two
        URLs. 404 rather than a redirect is deliberate — the two addresses were
        never equivalent, so there is no old address to forward from.
        """
        if await public_claims.claimed_url(db, slug, locale) is not None:
            raise HTTPException(status_code=404, detail="Page not found")
        return await render_public_page(
            slug, request, inertia, db, settings, locale=locale
        )

    return router


def default_locale_alias_router(settings: PagebuilderSettings) -> APIRouter:
    """``/{default}/p/{slug}`` → ``/p/{slug}``, permanently.

    The default language serves unprefixed so existing links keep working, but
    an author who has just used ``/de/p/x`` will reasonably try ``/en/p/x``, and
    so will anything that builds URLs by pasting a locale in front. Answering
    404 there would be technically correct and useless; serving the page at
    both would put one document at two addresses, which is the duplicate-content
    problem the whole prefix scheme exists to avoid. A 301 is the third option
    and the only good one.
    """
    router = APIRouter(dependencies=[Depends(bind_public)])

    @router.get("/{slug}", response_model=None)
    async def redirect_to_unprefixed(slug: str) -> RedirectResponse:
        return RedirectResponse(
            f"{settings.public_route_prefix.rstrip('/')}/{slug}", status_code=301
        )

    return router
