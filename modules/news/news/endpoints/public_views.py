"""The public article viewer.

News owns the address *and* the rendering now. It used to own only the address:
the route resolved a slug and handed off to pagebuilder's viewer, because the
body was a page in that module and duplicating the viewer would have meant
duplicating its ETag, cache, CSP, canonical and redirect handling.

That trade is gone with the sidecar. The body is a column here, so this is the
one place that can serve it — and everything the old hand-off preserved is
below, over this module's own rows.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from news import constants, redirects
from news.content import ArticlesService
from news.models import NOT_TRASHED, ArticleStatus, NewsArticle
from news.settings import NewsSettings, active, public_article_path

public_router = APIRouter()


def _etag_for(article_id: int, updated_at: datetime | None) -> str:
    """Stable, short ETag derived from identity + last-modified time.

    Deliberately not a hash of the payload: the body is the biggest column in
    the table, and hashing it on every request would make a conditional GET cost
    more than an unconditional one.
    """
    stamp = updated_at.isoformat() if updated_at is not None else ""
    digest = hashlib.sha1(f"{article_id}:{stamp}".encode()).hexdigest()[:16]
    return f'W/"{digest}"'


def _public_base_url(request: Request, settings: NewsSettings) -> str:
    """Resolve the public origin used to build absolute URLs.

    Prefer the explicit setting — the deployment knows its public host — and
    only fall back to the inbound request for local development and scenarios
    where the Host header is trustworthy. Always returned without a trailing
    slash so callers can concatenate path segments directly.
    """
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    return f"{request.url.scheme}://{request.url.netloc}".rstrip("/")


def _absolute_url(request: Request, settings: NewsSettings, slug: str) -> str:
    return f"{_public_base_url(request, settings)}{public_article_path(slug)}"


def _cache_control(settings: NewsSettings) -> str:
    parts = [f"max-age={settings.public_cache_max_age}"]
    if settings.public_cache_swr > 0:
        parts.append(f"stale-while-revalidate={settings.public_cache_swr}")
    return "public, " + ", ".join(parts)


async def sitemap_entries(db: AsyncSession) -> list[tuple[str, datetime | None]]:
    """Slug + last-modified of every published, indexable article.

    Two columns, not entities: loading rows whole would drag both block-JSON
    columns through the ORM on every crawl, which at a few thousand articles is
    tens of MB per request.
    """
    rows = await db.execute(
        select(NewsArticle.slug, NewsArticle.updated_at)
        .where(
            NOT_TRASHED,
            NewsArticle.status == ArticleStatus.PUBLISHED,
            NewsArticle.index_in_search.is_(True),
        )
        .order_by(NewsArticle.updated_at.desc())
    )
    return [(slug, updated_at) for slug, updated_at in rows.all()]


# Declared before ``/{slug}``, and that ordering is load-bearing: FastAPI
# matches in registration order, so the catch-all below would otherwise treat
# "sitemap.xml" as an article slug and answer 404.
@public_router.get("/sitemap.xml", response_model=None)
async def article_sitemap(
    request: Request, db: AsyncSession = Depends(get_db)
) -> Response:
    """Every published article, for a crawler.

    Articles used to reach one through pagebuilder's sitemap, because they were
    pages in it — see the ``public_claims`` hook that made that work. They are
    not pages any more, so this module advertises its own or the archive
    silently drops out of every index.
    """
    settings = active()
    base = _public_base_url(request, settings)
    urls = "".join(
        "<url>"
        f"<loc>{base}{public_article_path(slug)}</loc>"
        + (f"<lastmod>{updated_at.date().isoformat()}</lastmod>" if updated_at else "")
        + "</url>"
        for slug, updated_at in await sitemap_entries(db)
    )
    return Response(
        content=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{urls}</urlset>"
        ),
        media_type="application/xml",
        headers={"Cache-Control": _cache_control(settings)},
    )


@public_router.get("/{slug}", response_model=None)
async def public_article(
    slug: str,
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """One published article, with everything a public URL needs.

    A draft, a trashed article and a slug that was never an article all answer
    the same 404. A distinguishable "exists but is not published" would answer
    exactly the question the 404 is there to refuse.
    """
    settings = active()
    article = await ArticlesService(db).get_by_slug_published(slug)
    if article is None or article.published_data is None:
        # Before giving up: renaming an article records a redirect, and the old
        # address has to honour it or a rename silently breaks every link
        # already published.
        moved = await redirects.resolve(db, slug)
        if moved is not None:
            return RedirectResponse(public_article_path(moved), status_code=301)
        raise HTTPException(status_code=404, detail="Article not found")

    etag = _etag_for(article.id or 0, article.updated_at)
    cache_control = _cache_control(settings)

    def apply_headers(response: Response) -> Response:
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = cache_control
        if settings.public_csp:
            response.headers["Content-Security-Policy"] = settings.public_csp
        return response

    if request.headers.get("if-none-match") == etag:
        return apply_headers(Response(status_code=304))

    canonical = article.canonical_url or _absolute_url(request, settings, slug)
    return apply_headers(
        await inertia.render(
            constants._PAGE_PUBLIC_ARTICLE,
            {
                "title": article.title,
                # Which article this is, for the blocks in its own body that
                # need to know. `Related` is the one: a "read next" list that
                # includes the article you are reading is visibly broken, and
                # the slug is the only thing that identifies it inside the
                # block document.
                "slug": article.slug,
                # The published snapshot, never the draft — that is the whole
                # point of keeping two columns.
                "data": article.published_data,
                "meta_description": article.meta_description,
                "og_image": article.og_image,
                "canonical_url": canonical,
                "og_url": canonical,
                "index_in_search": article.index_in_search,
                "json_ld": article.json_ld,
                "site_name": settings.site_name or None,
                "twitter_handle": settings.twitter_handle or None,
                "category": article.category,
                "author": article.author,
                "published_at": (
                    article.published_at.isoformat()
                    if article.published_at is not None
                    else None
                ),
            },
        )
    )

