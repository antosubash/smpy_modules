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

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from news import constants, redirects
from news.content import ArticlesService
from news.endpoints.public import _head
from news.endpoints.public._urls import absolute_article, cache_control, etag_for
from news.settings import active, public_article_path

article_router = APIRouter()


@article_router.get("/{slug}", response_model=None)
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

    etag = etag_for(article.id or 0, article.updated_at)
    control = cache_control(settings)

    def apply_headers(response: Response) -> Response:
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = control
        if settings.public_csp:
            response.headers["Content-Security-Policy"] = settings.public_csp
        return response

    if request.headers.get("if-none-match") == etag:
        return apply_headers(Response(status_code=304))

    canonical = article.canonical_url or absolute_article(request, settings, slug)
    published_at = (
        article.published_at.isoformat() if article.published_at is not None else None
    )
    rendered = await inertia.render(
        constants._PAGE_PUBLIC_ARTICLE,
        {
            "title": article.title,
            # Which article this is, for the blocks in its own body that need to
            # know. `Related` is the one: a "read next" list that includes the
            # article you are reading is visibly broken, and the slug is the
            # only thing that identifies it inside the block document.
            "slug": article.slug,
            # The published snapshot, never the draft — that is the whole point
            # of keeping two columns.
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
            "published_at": published_at,
        },
    )

    # The same tags `PublicArticle` renders through Inertia's `<Head>`, written
    # into the document server-side — see `_head` for why both are needed.
    return apply_headers(
        _head.inject(
            rendered,
            _head.article_head(
                title=article.title,
                description=article.meta_description or None,
                canonical=canonical,
                image=article.og_image or None,
                site_name=settings.site_name or None,
                twitter_handle=settings.twitter_handle or None,
                published_at=published_at,
                author=article.author or None,
                section=article.category or None,
                index_in_search=article.index_in_search,
                json_ld=article.json_ld,
            ),
        )
    )
