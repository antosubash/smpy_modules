"""Public ``/sitemap.xml`` and ``/robots.txt`` routes (issue #24).

Mounted directly on the host app from ``on_startup`` (alongside
``/p/{slug}``) so the URLs sit at the site root, not under the admin
prefix. Both routes are short-cached so a busy crawler doesn't hammer
the page-list query, and both honour per-page ``index_in_search`` so a
``noindex`` page is also kept out of discovery.
"""

from __future__ import annotations

from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Depends, Request, Response
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder import locales, public_claims
from pagebuilder.deps import get_settings
from pagebuilder.service import PagesService
from pagebuilder.settings import PagebuilderSettings

seo_router = APIRouter()


def _public_origin(request: Request, settings: PagebuilderSettings) -> str:
    """Same fallback as the public viewer: explicit setting wins, else inferred."""
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    return f"{request.url.scheme}://{request.url.netloc}".rstrip("/")


def _sitemap_url_for(origin: str, prefix: str, slug: str, locale: str) -> str:
    return f"{origin}{locales.public_path(prefix, slug, locale)}"


_XHTML_NS = "http://www.w3.org/1999/xhtml"

# Attribute values need the quote escaped as well as the three characters
# ``xml_escape`` handles by default — a URL is free to contain one.
_ATTR_ESCAPES = {'"': "&quot;"}


def _attr(value: str) -> str:
    return xml_escape(value, _ATTR_ESCAPES)


def _alternate_links(alternates: list[tuple[str, str]]) -> str:
    """``xhtml:link`` entries naming this URL's counterparts in other languages.

    Emitted alongside the on-page ``hreflang`` tags rather than instead of
    them: the sitemap is what lets a crawler discover a translation without
    having fetched its source first, which for a page nothing links to yet is
    the difference between indexed and invisible.

    Empty for a page with no published, indexable counterpart — which is every
    page on a monolingual site.
    """
    if len(alternates) < 2:
        return ""
    links = [
        f'<xhtml:link rel="alternate" hreflang="{_attr(locale)}" href="{_attr(url)}"/>'
        for locale, url in alternates
    ]
    default = next((url for locale, url in alternates if locales.is_default(locale)), None)
    if default is not None:
        links.append(
            '<xhtml:link rel="alternate" hreflang="x-default" '
            f'href="{_attr(default)}"/>'
        )
    return "".join(links)


@seo_router.get("/sitemap.xml", response_class=Response)
async def sitemap(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: PagebuilderSettings = Depends(get_settings),
) -> Response:
    if not settings.sitemap_enabled:
        return Response(status_code=404)

    # Column-only query: at a few thousand pages, loading full entities
    # (with both block-JSON columns) made every crawl a multi-second,
    # tens-of-MB request (issue #11).
    pages = await PagesService(db).list_sitemap_entries()
    origin = _public_origin(request, settings)
    prefix = settings.public_route_prefix
    # A page another module serves the public URL for is advertised at *that*
    # address. Without this the sitemap would point a crawler at /p/{slug},
    # which the viewer now refuses for exactly those pages.
    #
    # Asked once per language rather than once per slug: a claim answers about
    # one locale at a time, and a four-language site would otherwise make four
    # times the queries it needs. Keyed by ``(locale, slug)`` on the way back
    # out, because the same slug in two languages is two different pages.
    claimed: dict[tuple[str, str], str] = {}
    for locale in {page.locale for page in pages}:
        in_locale = [page.slug for page in pages if page.locale == locale]
        for slug, url in (await public_claims.resolve(db, in_locale, locale)).items():
            claimed[(locale, slug)] = url

    def absolute(page) -> str:
        claim = claimed.get((page.locale, page.slug))
        if claim:
            return f"{origin}{claim}"
        return _sitemap_url_for(origin, prefix, page.slug, page.locale)

    # Built before the entry loop so each URL can name every *other* language's
    # address, including ones that sort after it.
    alternates: dict[str, list[tuple[str, str]]] = {}
    for page in pages:
        alternates.setdefault(page.translation_group, []).append(
            (page.locale, absolute(page))
        )

    entries: list[str] = []
    for page in pages:
        loc = xml_escape(absolute(page))
        links = _alternate_links(alternates[page.translation_group])
        lastmod = page.updated_at.isoformat() if page.updated_at else None
        modified = (
            f"<lastmod>{xml_escape(lastmod)}</lastmod>" if lastmod is not None else ""
        )
        entries.append(f"  <url><loc>{loc}</loc>{modified}{links}</url>")

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        f'xmlns:xhtml="{_XHTML_NS}">\n'
        + "\n".join(entries)
        + ("\n" if entries else "")
        + "</urlset>\n"
    )
    return Response(
        content=body,
        media_type="application/xml",
        headers={"Cache-Control": f"public, max-age={settings.seo_cache_max_age}"},
    )


@seo_router.get("/robots.txt", response_class=Response)
async def robots(
    request: Request,
    settings: PagebuilderSettings = Depends(get_settings),
) -> Response:
    if not settings.robots_enabled:
        return Response(status_code=404)

    if settings.robots_body is not None:
        body = settings.robots_body
    else:
        lines = ["User-agent: *", "Allow: /"]
        if settings.sitemap_enabled:
            origin = _public_origin(request, settings)
            lines.append(f"Sitemap: {origin}/sitemap.xml")
        body = "\n".join(lines) + "\n"

    return Response(
        content=body,
        media_type="text/plain",
        headers={"Cache-Control": f"public, max-age={settings.seo_cache_max_age}"},
    )
