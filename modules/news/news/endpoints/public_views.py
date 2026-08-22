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

One router per content locale, mounted at ``/news/{slug}`` for the site's
default language and ``/{locale}/news/{slug}`` for every other, mirroring how
pagebuilder addresses pages. A slug identifies an article only within one
language, so the locale is a parameter of every lookup here rather than
something inferred later.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from news.integrations.locales import default_locale
from news.integrations.pagebuilder import (
    NOT_TRASHED,
    Page,
    PageStatus,
    redirected_slug,
    render_article_page,
)
from news.models import NewsArticle
from news.settings import public_article_path


async def published_article_slugs(
    db: AsyncSession, slugs: Sequence[str], locale: str | None = None
) -> set[str]:
    """Which of these slugs belong to a published, untrashed article in ``locale``.

    One query for the whole set: the sitemap asks about every published page at
    once, so a per-slug lookup would make a crawl as many round trips deep as
    the site has pages.

    ``locale`` defaults to the site's own, which is what a caller that predates
    the language dimension means by an unqualified slug.
    """
    if not slugs:
        return set()
    rows = await db.execute(
        select(Page.slug)
        .join(NewsArticle, NewsArticle.page_id == Page.id)
        .where(
            NOT_TRASHED,
            Page.status == PageStatus.PUBLISHED,
            Page.locale == (locale or default_locale()),
            Page.slug.in_(slugs),
        )
    )
    return set(rows.scalars())


def slug_claim():
    """The claim news registers with pagebuilder — ``{slug: news URL}``.

    The URL comes from the same ``public_article_path`` the listing API serves
    in ``ArticleRead.url``, so the address a crawler is sent to and the address
    the admin list shows cannot disagree — including the language prefix.
    """

    async def claim(
        db: AsyncSession, slugs: Sequence[str], locale: str
    ) -> Mapping[str, str]:
        owned = await published_article_slugs(db, slugs, locale)
        return {slug: public_article_path(slug, locale) for slug in owned}

    return claim


def locale_router(locale: str) -> APIRouter:
    """The article viewer for one language.

    A router per locale rather than a ``/{locale}`` path parameter, for the
    same reason pagebuilder does it: a parameter matches *any* first segment,
    and the public-route registry exempts by string prefix — so the exemption
    would have to be widened to something that no longer describes what is
    public.
    """
    router = APIRouter()

    @router.get("/{slug}", response_model=None)
    async def public_article(
        slug: str,
        request: Request,
        inertia: InertiaDep,
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        """One article, rendered by pagebuilder's viewer at news' address."""
        prefix = request.app.state.news.settings.public_route_prefix
        if not await published_article_slugs(db, [slug], locale):
            # Before giving up: renaming an article records a redirect, exactly
            # as renaming any other page does, and the old news address has to
            # honour it or a rename silently breaks every link already
            # published.
            #
            # Only when the rename lands on an article, though. A plain page
            # that once used this slug must not be served here — this prefix
            # means articles — and forwarding to an address that would itself
            # 404 is worse than saying so now.
            #
            # Within this language, and only this one: an old German address
            # forwarding to the English article would answer the question
            # "where did my page go" with someone else's page.
            moved = await redirected_slug(db, slug, locale)
            if moved is not None and await published_article_slugs(db, [moved], locale):
                return RedirectResponse(
                    url=public_article_path(moved, locale), status_code=301
                )
            # Not an article — or an article whose page is a draft or in the
            # trash. One message for all three: a distinguishable "exists but
            # is not published" would answer the question the 404 is there to
            # refuse.
            raise HTTPException(status_code=404, detail="Article not found")
        return await render_article_page(
            slug, request, inertia, db, url_prefix=prefix, locale=locale
        )

    return router


def default_locale_alias_router(prefix: str) -> APIRouter:
    """``/{default}/news/{slug}`` → ``/news/{slug}``, permanently.

    The default language serves unprefixed so existing links keep working, but
    anyone who has seen ``/de/news/x`` will reasonably try ``/en/news/x``.
    Serving the article at both would put one document at two addresses;
    404ing would be correct and useless. A 301 is the third option.
    """
    router = APIRouter()

    @router.get("/{slug}", response_model=None)
    async def redirect_to_unprefixed(slug: str) -> RedirectResponse:
        return RedirectResponse(url=f"{prefix.rstrip('/')}/{slug}", status_code=301)

    return router
