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

from pagebuilder.deps import get_settings
from pagebuilder.service import PagesService
from pagebuilder.settings import PagebuilderSettings

seo_router = APIRouter()


def _public_origin(request: Request, settings: PagebuilderSettings) -> str:
    """Same fallback as the public viewer: explicit setting wins, else inferred."""
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    return f"{request.url.scheme}://{request.url.netloc}".rstrip("/")


def _sitemap_url_for(origin: str, prefix: str, slug: str) -> str:
    return f"{origin}{prefix.rstrip('/')}/{slug}"


@seo_router.get("/sitemap.xml", response_class=Response)
async def sitemap(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: PagebuilderSettings = Depends(get_settings),
) -> Response:
    if not settings.sitemap_enabled:
        return Response(status_code=404)

    pages = await PagesService(db).list_indexable_published()
    origin = _public_origin(request, settings)
    prefix = settings.public_route_prefix

    entries: list[str] = []
    for page in pages:
        loc = xml_escape(_sitemap_url_for(origin, prefix, page.slug))
        lastmod = page.updated_at.isoformat() if page.updated_at else None
        if lastmod is not None:
            entries.append(
                f"  <url><loc>{loc}</loc><lastmod>{xml_escape(lastmod)}</lastmod></url>"
            )
        else:
            entries.append(f"  <url><loc>{loc}</loc></url>")

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
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
