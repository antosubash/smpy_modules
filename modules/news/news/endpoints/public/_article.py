"""The public article viewer.

News owns the address *and* the rendering now. It used to own only the address:
the route resolved a slug and handed off to pagebuilder's viewer, because the
body was a page in that module and duplicating the viewer would have meant
duplicating its ETag, cache, CSP, canonical, ``hreflang`` and redirect handling.

That trade is gone with the sidecar. The body is a column here, so this is the
one place that can serve it — and everything the old hand-off preserved is
below, over this module's own rows.

One router per content locale, mounted at ``/news/{slug}`` for the site's
default language and ``/{locale}/news/{slug}`` for every other, mirroring how
pagebuilder addresses pages. A slug identifies an article only within one
language, so the locale is a parameter of every lookup here rather than
something inferred later.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from news import locales, redirects, service
from news.content import ArticlesService
from news.endpoints.public._render import render_article
from news.endpoints.public._urls import (
    absolute_article,
    cache_control,
    etag_for,
    public_base_url,
)
from news.safe_url import canonical_or_none
from news.settings import NewsSettings, active, public_article_path
from news.tenancy import bind_public


async def alternates(
    db: AsyncSession, request: Request, settings: NewsSettings, group: str | None
) -> list[dict[str, str]]:
    """``hreflang`` entries for every *published* article in the group.

    Only published ones — ``list_articles`` without ``include_drafts`` is
    exactly that rule: advertising a draft translation points a crawler at a 404
    and offers a reader a language switch that dead-ends.

    Read through the ordinary listing rather than a query of its own, so the
    address advertised here is the same string the admin list and the feed show.
    ``ArticleRead.url`` is built from ``public_article_path``, language prefix
    and all, and a second way of assembling it is a second chance to disagree.

    Omitted entirely when the group has one published member, which is every
    article on a monolingual site — a lone ``hreflang`` pointing at the document
    itself says nothing and is noise in the head of every page.

    A site with one content locale is answered without asking the database at
    all. It cannot have a second member, and this runs on every public article
    render: a query per page view to reach a guaranteed empty list is the kind
    of cost a monolingual host should not pay for a feature it does not use.
    """
    languages = locales.supported()
    if not group or len(languages) < 2:
        return []
    siblings, _ = await service.list_articles(
        db,
        # One per language and no more; a group cannot hold two of the same.
        limit=len(languages),
        group=group,
        with_total=False,
    )
    if len(siblings) < 2:
        return []
    base = public_base_url(request, settings)
    entries = [
        {"locale": item.locale, "url": f"{base}{item.url}"} for item in siblings
    ]
    # x-default names the version to serve someone whose language nobody
    # matched. The site's own default is the only defensible answer.
    default = next((e for e in entries if locales.is_default(e["locale"])), None)
    if default is not None:
        entries.append({"locale": "x-default", "url": default["url"]})
    return entries


def article_router(locale: str) -> APIRouter:
    """The article viewer for one language.

    A router per locale rather than a ``/{locale}`` path parameter, for the same
    reason pagebuilder does it: a parameter matches *any* first segment, and the
    public-route registry exempts by string prefix — so the exemption would have
    to be widened to something that no longer describes what is public.
    """
    router = APIRouter()

    @router.get("/{slug}", response_model=None)
    async def public_article(
        slug: str,
        request: Request,
        inertia: InertiaDep,
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        """One published article, with everything a public URL needs.

        A draft, a trashed article and a slug that was never an article all
        answer the same 404. A distinguishable "exists but is not published"
        would answer exactly the question the 404 is there to refuse.
        """
        settings = active()
        article = await ArticlesService(db).get_by_slug_published(slug, locale)
        if article is None or article.published_data is None:
            # Before giving up: renaming an article records a redirect, and the
            # old address has to honour it or a rename silently breaks every
            # link already published.
            #
            # Within this language, and only this one: an old German address
            # forwarding to the English article would answer the question
            # "where did my page go" with someone else's article.
            moved = await redirects.resolve(db, slug, locale)
            if moved is not None:
                return RedirectResponse(
                    public_article_path(moved, locale), status_code=301
                )
            raise HTTPException(status_code=404, detail="Article not found")

        variant = "inertia" if request.headers.get("x-inertia") else "html"
        etag = etag_for(article.id or 0, article.updated_at, variant)
        control = cache_control(settings)

        def apply_headers(response: Response) -> Response:
            response.headers["ETag"] = etag
            # The same URL serves two representations; see `etag_for`.
            response.headers["Vary"] = "X-Inertia"
            response.headers["Cache-Control"] = control
            # Which language was served, for caches and for anything reading
            # the response without parsing the body.
            response.headers["Content-Language"] = locale
            if settings.public_csp:
                response.headers["Content-Security-Policy"] = settings.public_csp
            return response

        if request.headers.get("if-none-match") == etag:
            return apply_headers(Response(status_code=304))

        canonical = canonical_or_none(article.canonical_url) or absolute_article(
            request, settings, slug, locale
        )
        siblings = await alternates(db, request, settings, article.translation_group)
        # Everything from here is shared with the authenticated preview — see
        # `_render`. The one thing that is not shared is the argument below:
        # this route serves the published snapshot, never the draft, which is
        # the whole point of keeping two columns.
        return apply_headers(
            await render_article(
                inertia,
                article=article,
                data=article.published_data,
                locale=locale,
                settings=settings,
                canonical=canonical,
                alternates=siblings,
                index_in_search=article.index_in_search,
            )
        )

    return router


def default_locale_alias_router(prefix: str) -> APIRouter:
    """``/{default}/news/{slug}`` → ``/news/{slug}``, permanently.

    The default language serves unprefixed so existing links keep working, but
    anyone who has seen ``/de/news/x`` will reasonably try ``/en/news/x``, and so
    will anything that builds URLs by pasting a locale in front. Serving the
    article at both would put one document at two addresses; 404ing would be
    correct and useless. A 301 is the third option and the only good one.

    Bound like every public router although it reads no rows: it costs nothing,
    and the route guard then needs no exception a later edit could outgrow.
    """
    router = APIRouter(dependencies=[Depends(bind_public)])

    @router.get("/{slug}", response_model=None)
    async def redirect_to_unprefixed(slug: str) -> RedirectResponse:
        return RedirectResponse(f"{prefix.rstrip('/')}/{slug}", status_code=301)

    return router
