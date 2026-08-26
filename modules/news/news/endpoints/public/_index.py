"""The archive's front door: an index, and one page per category and tag.

These did not exist until now, and their absence was the hole in the middle of
the split. News could be installed on its own and served on its own, but a
reader could only ever reach an article they already had a link to: the only
route was ``/{slug}``, so ``/news/`` answered 404 and ``/news`` bounced an
anonymous visitor to the sign-in screen. The one browsing surface, the
``NewsFeed`` block, registers into *pagebuilder's* palette — so the module that
was made independent could not be read independently.

Paged rather than infinite: a crawler follows links, and "load more" is not one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from news import constants, service
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

index_router = APIRouter()

PAGE_SIZE = 12
"""Articles per archive page.

Twelve rather than the API's default: this is a reading surface, and the number
that suits a JSON client fetching a sidebar is not the number that fills a page.
"""


async def _render_archive(
    *,
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession,
    page: int,
    path: str,
    heading: str,
    description: str | None = None,
    category: str | None = None,
    tag: str | None = None,
) -> Response:
    """One archive page, however it was narrowed.

    The index, a category and a tag differ only in what they filter by and what
    they call themselves, so they share everything else — the paging, the
    canonical link, the cache policy and the head.
    """
    settings: NewsSettings = active()
    items, total = await service.list_articles(
        db,
        limit=PAGE_SIZE,
        offset=(page - 1) * PAGE_SIZE,
        category=category,
        tag=tag,
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
            "feed_url": public_feed_path(),
            "site_name": settings.site_name or None,
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
            feed_url=absolute(request, settings, public_feed_path()),
        ),
    )
    response.headers["Cache-Control"] = listing_cache_control(settings)
    return response


# Registered before ``/{slug}``. Two segments cannot collide with an article
# slug, but ``/`` and the router order still matter — see the package's
# ``__init__``.
@index_router.get("/", response_model=None)
async def archive_index(
    request: Request,
    inertia: InertiaDep,
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Everything published, newest first."""
    return await _render_archive(
        request=request,
        inertia=inertia,
        db=db,
        page=page,
        path=public_index_path(),
        heading=active().site_name or "News",
    )


@index_router.get("/category/{slug}", response_model=None)
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
    name = await db.scalar(select(NewsCategory.name).where(NewsCategory.slug == slug))
    return await _render_archive(
        request=request,
        inertia=inertia,
        db=db,
        page=page,
        path=public_category_path(slug),
        heading=name or slug,
        description=f"Articles in {name or slug}.",
        category=name or slug,
    )


@index_router.get("/tag/{slug}", response_model=None)
async def archive_tag(
    slug: str,
    request: Request,
    inertia: InertiaDep,
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """One tag's archive.

    Unknown tags render an empty archive rather than 404ing: a tag can be
    removed from the last article carrying it, and the URL that was published
    while it existed should say "nothing here now", not "never existed".
    """
    name = await db.scalar(select(NewsTag.name).where(NewsTag.slug == slug))
    return await _render_archive(
        request=request,
        inertia=inertia,
        db=db,
        page=page,
        path=public_tag_path(slug),
        heading=f"#{name or slug}",
        description=f"Articles tagged {name or slug}.",
        tag=slug,
    )
