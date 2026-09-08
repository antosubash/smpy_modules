"""The archive's front door: an index, and one page per category and tag.

These did not exist until now, and their absence was the hole in the middle of
the split. News could be installed on its own and served on its own, but a
reader could only ever reach an article they already had a link to: the only
route was ``/{slug}``, so ``/news/`` answered 404 and ``/news`` bounced an
anonymous visitor to the sign-in screen. The one browsing surface, the
``NewsFeed`` block, registers into *pagebuilder's* palette — so the module that
was made independent could not be read independently.

Paged rather than infinite: a crawler follows links, and "load more" is not one.

One router per content locale, like the article viewer beside it. An archive
that mixed languages would be a reading surface nobody could read: the German
index lists German articles, at German addresses, and says so in its
``hreflang``.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from news import constants, locales, service
from news.endpoints.public import _head
from news.endpoints.public._urls import absolute, listing_cache_control
from news.models import NewsCategory, NewsTag
from news.settings import (
    NewsSettings,
    active,
    public_category_path,
    public_feed_path,
    public_index_path,
    public_tag_path,
)

PAGE_SIZE = 12
"""Articles per archive page.

Twelve rather than the API's default: this is a reading surface, and the number
that suits a JSON client fetching a sidebar is not the number that fills a page.
"""


def _archive_alternates(
    request: Request, settings: NewsSettings, path_for: Callable[[str], str]
) -> list[dict[str, str]]:
    """The same archive page in every other language.

    No query behind it, unlike an article's: an archive exists in each language
    by construction — every locale has an index, and a category or tag page for
    any slug — so the set of addresses is derivable rather than something to
    look up. Empty on a monolingual site, where a lone self-referential
    ``hreflang`` would be noise.
    """
    languages = locales.supported()
    if len(languages) < 2:
        return []
    entries = [
        {"locale": locale, "url": absolute(request, settings, path_for(locale))}
        for locale in languages
    ]
    default = next((e for e in entries if locales.is_default(e["locale"])), None)
    if default is not None:
        entries.append({"locale": "x-default", "url": default["url"]})
    return entries


async def _render_archive(
    *,
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession,
    locale: str,
    page: int,
    path_for: Callable[[str], str],
    heading: str,
    description: str | None = None,
    category: str | None = None,
    tag: str | None = None,
) -> Response:
    """One archive page, however it was narrowed.

    The index, a category and a tag differ only in what they filter by and what
    they call themselves, so they share everything else — the paging, the
    canonical link, the cache policy and the head.

    ``path_for`` builds this page's address in a given language rather than
    being handed a finished path, because the canonical link and the
    ``hreflang`` set are the same address in different languages and deriving
    one from the other is what keeps them from drifting.
    """
    settings: NewsSettings = active()
    path = path_for(locale)
    items, total = await service.list_articles(
        db,
        limit=PAGE_SIZE,
        offset=(page - 1) * PAGE_SIZE,
        category=category,
        tag=tag,
        locale=locale,
        # An archive lists what is published, and honours the same
        # "keep this out of feeds" flag the feed block does: an article held
        # back from listings should not reappear in the one listing that is the
        # site's front door.
        in_feed_only=True,
    )
    pages = max(1, -(-total // PAGE_SIZE))
    if page > pages and total:
        # Past the end is a 404 rather than an empty page, so a crawler that
        # guesses ?page=900 is told there is nothing there instead of being
        # handed a valid-looking empty document to index.
        raise HTTPException(status_code=404, detail="No such page")

    canonical = absolute(request, settings, path if page == 1 else f"{path}?page={page}")
    feed_path = public_feed_path(locale)
    rendered = await inertia.render(
        constants._PAGE_PUBLIC_INDEX,
        {
            "heading": heading,
            "description": description,
            "items": [item.model_dump(mode="json") for item in items],
            "page": page,
            "pages": pages,
            "total": total,
            "base_path": path,
            "feed_url": feed_path,
            "site_name": settings.site_name or None,
            "locale": locale,
        },
    )
    response = _head.inject(
        rendered,
        _head.listing_head(
            title=(
                heading
                if not settings.site_name
                else f"{heading} — {settings.site_name}"
            ),
            description=description,
            canonical=canonical,
            site_name=settings.site_name or None,
            feed_url=absolute(request, settings, feed_path),
            locale=locale,
            alternates=_archive_alternates(request, settings, path_for),
        ),
    )
    response.headers["Cache-Control"] = listing_cache_control(settings)
    response.headers["Content-Language"] = locale
    return response


def index_router(locale: str) -> APIRouter:
    """The archive for one language.

    Registered before ``/{slug}``. Two segments cannot collide with an article
    slug, but ``/`` and the router order still matter — see the package's
    ``__init__``.
    """
    router = APIRouter()

    @router.get("/", response_model=None)
    async def archive_index(
        request: Request,
        inertia: InertiaDep,
        page: int = Query(1, ge=1),
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        """Everything published in this language, newest first."""
        return await _render_archive(
            request=request,
            inertia=inertia,
            db=db,
            locale=locale,
            page=page,
            path_for=lambda loc: public_index_path(locale=loc),
            heading=active().site_name or "News",
        )

    @router.get("/category/{slug}", response_model=None)
    async def archive_category(
        slug: str,
        request: Request,
        inertia: InertiaDep,
        page: int = Query(1, ge=1),
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        """One category's archive.

        A category nobody formalised on the categories screen has no row, so the
        slug is matched against the managed rows first and falls back to the raw
        value — the same rule the listing API already applies.
        """
        name = await db.scalar(
            select(NewsCategory.name).where(NewsCategory.slug == slug)
        )
        return await _render_archive(
            request=request,
            inertia=inertia,
            db=db,
            locale=locale,
            page=page,
            path_for=lambda loc: public_category_path(slug, loc),
            heading=name or slug,
            description=f"Articles in {name or slug}.",
            category=name or slug,
        )

    @router.get("/tag/{slug}", response_model=None)
    async def archive_tag(
        slug: str,
        request: Request,
        inertia: InertiaDep,
        page: int = Query(1, ge=1),
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        """One tag's archive.

        Unknown tags render an empty archive rather than 404ing: a tag can be
        removed from the last article carrying it, and the URL that was
        published while it existed should say "nothing here now", not "never
        existed".
        """
        name = await db.scalar(select(NewsTag.name).where(NewsTag.slug == slug))
        return await _render_archive(
            request=request,
            inertia=inertia,
            db=db,
            locale=locale,
            page=page,
            path_for=lambda loc: public_tag_path(slug, loc),
            heading=f"#{name or slug}",
            description=f"Articles tagged {name or slug}.",
            tag=slug,
        )

    return router
