"""The public address an article serves at.

An article *is* a page, so the body, the workflow and the rendering all belong
to pagebuilder. What this module took back is the **URL**: articles used to sit
at ``/p/{slug}`` alongside every other page, so the address said nothing about
what the document was and nothing could tell an article from a contact form in
a log line or an analytics report.

The rendering is still pagebuilder's — this route resolves the slug to a
published article and hands off. A slug that is not an article is not served
here even if a page by that name exists and is published: this prefix means
articles, and answering with an ordinary page would make it mean nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from news.integrations.pagebuilder import (
    NOT_TRASHED,
    Page,
    PageStatus,
    redirected_slug,
    render_article_page,
)
from news.models import NewsArticle
from news.settings import public_article_path

public_router = APIRouter()


async def published_article_slugs(
    db: AsyncSession, slugs: Sequence[str]
) -> set[str]:
    """Which of these slugs belong to a published, untrashed article.

    One query for the whole set: the sitemap asks about every published page at
    once, so a per-slug lookup would make a crawl as many round trips deep as
    the site has pages.
    """
    if not slugs:
        return set()
    rows = await db.execute(
        select(Page.slug)
        .join(NewsArticle, NewsArticle.page_id == Page.id)
        .where(NOT_TRASHED, Page.status == PageStatus.PUBLISHED, Page.slug.in_(slugs))
    )
    return set(rows.scalars())


def slug_claim():
    """The claim news registers with pagebuilder — ``{slug: news URL}``.

    The URL comes from the same ``public_article_path`` the listing API serves
    in ``ArticleRead.url``, so the address a crawler is sent to and the address
    the admin list shows cannot disagree.
    """

    async def claim(db: AsyncSession, slugs: Sequence[str]) -> Mapping[str, str]:
        owned = await published_article_slugs(db, slugs)
        return {slug: public_article_path(slug) for slug in owned}

    return claim


@public_router.get("/{slug}", response_model=None)
async def public_article(
    slug: str,
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """One article, rendered by pagebuilder's viewer at news' address."""
    prefix = request.app.state.news.settings.public_route_prefix
    if not await published_article_slugs(db, [slug]):
        # Before giving up: renaming an article records a redirect, exactly as
        # renaming any other page does, and the old news address has to honour
        # it or a rename silently breaks every link already published.
        #
        # Only when the rename lands on an article, though. A plain page that
        # once used this slug must not be served here — this prefix means
        # articles — and forwarding to an address that would itself 404 is
        # worse than saying so now.
        moved = await redirected_slug(db, slug)
        if moved is not None and await published_article_slugs(db, [moved]):
            return RedirectResponse(url=public_article_path(moved), status_code=301)
        # Not an article — or an article whose page is a draft or in the trash.
        # One message for all three: a distinguishable "exists but is not
        # published" would answer the question the 404 is there to refuse.
        raise HTTPException(status_code=404, detail="Article not found")
    return await render_article_page(slug, request, inertia, db, url_prefix=prefix)
