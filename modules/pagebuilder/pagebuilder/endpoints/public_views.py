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

import json
import warnings

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder import locales, public_cache, redirects, site_nav
from pagebuilder.deps import get_settings
from pagebuilder.layout_service import LayoutService, public_layout_props
from pagebuilder.og_image import og_image
from pagebuilder.service import PagesService
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.tenancy import bind_public, vary_on_tenant

_PAGE_PUBLIC = "PageBuilder/PublicPage"


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

    Omitted entirely when the group has one member, which is every page on a
    monolingual site — a lone ``hreflang`` pointing at the page itself says
    nothing and is noise in the head of every document.
    """
    published = await PagesService(db).published_alternates(group)
    if len(published) < 2:
        return []
    alternates = [
        {
            "locale": locale,
            "url": _absolute_page_url(
                request, settings, slug, settings.public_route_prefix, locale
            ),
        }
        for locale, slug in published
    ]
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
    locale: str,
    url_prefix: str | None = None,
) -> Response:
    """Serve a published page, with everything a public URL needs: ETag, cache,
    CSP, canonical, ``hreflang`` and old-slug handling.

    ``locale`` is which language's page to look for, and is required with no
    fallback to the default language: a caller that forgot it would be served
    the default-language page at a translated address, which is how
    ``/de/p/x`` starts serving the English one.

    ``url_prefix`` is deprecated (#132). It was the claimant module's address,
    from the ``public_claims`` hook that has since been removed, and is kept so
    a host that still passes it keeps working: it sets the canonical URL and
    the old-slug redirect target, exactly as before. The hreflang alternates,
    sitemap and nav always use this module's own prefix. Omit it.
    """
    if url_prefix is not None:
        warnings.warn(
            "render_public_page(url_prefix=...) is deprecated and will be "
            "removed; the page is served at the module's own public_route_prefix",
            DeprecationWarning,
            stacklevel=2,
        )
    prefix = url_prefix if url_prefix is not None else settings.public_route_prefix
    page = await PagesService(db).get_by_slug_published(slug, locale)
    if page is None or page.published_data is None:
        # Before giving up: this may be an address the page used to live at.
        moved_to = await redirects.resolve(db, slug, locale)
        if moved_to is not None:
            target = locales.public_path(prefix, moved_to, locale)
            # A 301 is cacheable by default; key it on what picks the tenant.
            return vary_on_tenant(RedirectResponse(target, status_code=301), request)
        raise HTTPException(status_code=404, detail="Page not found")

    layout = await LayoutService(db).get()
    nav = await site_nav.site_nav(db, settings.public_route_prefix, page.locale)
    variant = "inertia" if request.headers.get("x-inertia") else "html"
    etag = public_cache.etag_for(
        page.id or 0,
        page.updated_at,
        layout.updated_at,
        variant,
        json.dumps(nav, sort_keys=True),
        public_cache.viewer_key(request),
    )
    # Signed-in or not, and in which UI language, decide the bytes (#94). A
    # signed-in page is never kept, so it gets no validator and no 304.
    cache_control = public_cache.cache_control(request, settings)
    signed_in = public_cache.signed_in(request)

    def apply_headers(response: Response) -> Response:
        if not signed_in:
            response.headers["ETag"] = etag
        response.headers["Vary"] = public_cache.VARY
        response.headers["Cache-Control"] = cache_control
        # On a multi-tenant host the tenant can come from the session, not the
        # Host. After Cache-Control: it may mark the response private (#192).
        vary_on_tenant(response, request)
        # Which language was negotiated, for caches and for anything reading
        # the response without parsing the body.
        response.headers["Content-Language"] = page.locale
        if settings.public_csp:
            response.headers["Content-Security-Policy"] = settings.public_csp
        return response

    if not signed_in and request.headers.get("if-none-match") == etag:
        return apply_headers(Response(status_code=304))

    canonical = page.canonical_url or _absolute_page_url(
        request, settings, slug, prefix, page.locale
    )
    return apply_headers(
        await inertia.render(
            _PAGE_PUBLIC,
            {
                # The SEO panel promises "blank uses the page title".
                "title": (page.meta_title or "").strip() or page.title,
                "data": page.published_data,
                "meta_description": page.meta_description,
                "og_image": og_image(
                    page.og_image, page.published_data, _public_base_url(request, settings)
                ),
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
                "site_nav": nav,
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
    layout, alternates — runs in the request's tenant, and a request
    that resolved none gets the unknown-slug 404.
    """
    router = APIRouter(dependencies=[Depends(bind_public)])

    @router.api_route("/{slug}", methods=["GET", "HEAD"], response_model=None)
    async def public_view(
        slug: str,
        request: Request,
        inertia: InertiaDep,
        db: AsyncSession = Depends(get_db),
        settings: PagebuilderSettings = Depends(get_settings),
    ) -> Response:
        """A published page at this module's own address, in one language."""
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

    @router.api_route("/{slug}", methods=["GET", "HEAD"], response_model=None)
    async def redirect_to_unprefixed(slug: str) -> RedirectResponse:
        return RedirectResponse(
            f"{settings.public_route_prefix.rstrip('/')}/{slug}", status_code=301
        )

    return router
