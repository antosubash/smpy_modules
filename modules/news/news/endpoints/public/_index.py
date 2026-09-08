"""The archive's front door: an index, and one page per category, tag and byline.

These did not exist until now, and their absence was the hole in the middle of
the split. News could be installed on its own and served on its own, but a
reader could only ever reach an article they already had a link to: the only
route was ``/{slug}``, so ``/news/`` answered 404 and ``/news`` bounced an
anonymous visitor to the sign-in screen. The one browsing surface, the
``NewsFeed`` block, registers into *pagebuilder's* palette — so the module that
was made independent could not be read independently.

Paged rather than infinite: a crawler follows links, and "load more" is not one.

Every route here takes ``?q=``, because a search is a *narrowing* of the page it
was typed on rather than a surface of its own — see ``_archive.render_archive``.
That is also why there is no ``/search`` route: it would be a fifth way of
listing articles, addressed differently from the four that already exist and
unable to say which category it was searching.

One router per content locale, like the article viewer beside it. An archive
that mixed languages would be a reading surface nobody could read: the German
index lists German articles, at German addresses, and says so in its
``hreflang``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from news.authors import resolve as resolve_author
from news.endpoints.public._archive import render_archive
from news.models import NewsCategory, NewsTag
from news.settings import (
    active,
    public_author_path,
    public_category_path,
    public_index_path,
    public_tag_path,
)


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
        q: str | None = Query(None),
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        """Everything published in this language, newest first."""
        return await render_archive(
            request=request,
            inertia=inertia,
            db=db,
            locale=locale,
            page=page,
            q=q,
            path_for=lambda loc: public_index_path(locale=loc),
            heading=active().site_name or "News",
        )

    @router.get("/category/{slug}", response_model=None)
    async def archive_category(
        slug: str,
        request: Request,
        inertia: InertiaDep,
        page: int = Query(1, ge=1),
        q: str | None = Query(None),
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
        return await render_archive(
            request=request,
            inertia=inertia,
            db=db,
            locale=locale,
            page=page,
            q=q,
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
        q: str | None = Query(None),
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        """One tag's archive.

        Unknown tags render an empty archive rather than 404ing: a tag can be
        removed from the last article carrying it, and the URL that was
        published while it existed should say "nothing here now", not "never
        existed".
        """
        name = await db.scalar(select(NewsTag.name).where(NewsTag.slug == slug))
        return await render_archive(
            request=request,
            inertia=inertia,
            db=db,
            locale=locale,
            page=page,
            q=q,
            path_for=lambda loc: public_tag_path(slug, loc),
            heading=f"#{name or slug}",
            description=f"Articles tagged {name or slug}.",
            tag=slug,
        )

    @router.get("/author/{slug}", response_model=None)
    async def archive_author(
        slug: str,
        request: Request,
        inertia: InertiaDep,
        page: int = Query(1, ge=1),
        q: str | None = Query(None),
        db: AsyncSession = Depends(get_db),
    ) -> Response:
        """One byline's archive.

        The byline was a dead end before this: it is rendered on the article and
        emitted as ``article:author``, but a reader who liked a writer had
        nowhere to go. A category and a tag each had an archive; the person who
        wrote the piece did not.

        No author table behind it — the address is derived from the byline and
        resolved by slugging the stored ones back, which is also why more than
        one spelling can land here. :mod:`news.authors` has the reasoning.

        Empty rather than 404 for a byline nobody has published under, for the
        same reason an unknown tag is: an author can be edited off the last
        article carrying them, and the URL published while they had one should
        say "nothing here now".
        """
        names, display = await resolve_author(db, slug, locale)
        return await render_archive(
            request=request,
            inertia=inertia,
            db=db,
            locale=locale,
            page=page,
            q=q,
            path_for=lambda loc: public_author_path(slug, loc),
            heading=display or slug,
            description=f"Articles by {display or slug}.",
            authors=names,
        )

    return router
