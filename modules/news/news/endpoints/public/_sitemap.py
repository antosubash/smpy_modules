"""The sitemap: how the whole archive reaches an index.

Its own file, split from ``_feeds.py`` when the two together reached the repo's
300-line cap. They were written as a pair — both are documents for machines,
and neither is optional for an archive — but they answer different machines,
and the language dimension is where that shows: **one sitemap** for the site,
listing every address in every language, because a crawler wants one document
telling it what exists rather than one per language it has to discover first.
The feed next door is per language, for the opposite reason.

Articles used to reach a crawler through pagebuilder's sitemap, because they
were pages in it. They are not pages any more, so this module advertises its
own or the archive silently drops out of every index.
"""

from __future__ import annotations

from datetime import datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Request, Response
from simple_module_db import get_db
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from news import locales
from news.authors import slug_for as author_slug
from news.endpoints.public._urls import cache_control, public_base_url
from news.models import (
    NOT_TRASHED,
    ArticleStatus,
    NewsArticle,
    NewsArticleTag,
    NewsCategory,
    NewsTag,
)
from news.settings import (
    active,
    public_article_path,
    public_author_path,
    public_category_path,
    public_index_path,
    public_tag_path,
)


async def sitemap_entries(
    db: AsyncSession,
) -> list[tuple[str, str, datetime | None]]:
    """Slug, language and last-modified of every published, indexable article.

    Three columns, not entities: loading rows whole would drag both block-JSON
    columns through the ORM on every crawl, which at a few thousand articles is
    tens of MB per request.

    The locale is one of them because it is half the address — ``budget`` names
    a different document in each language, and a sitemap that dropped it would
    advertise every translation at the default language's URL.
    """
    rows = await db.execute(
        select(NewsArticle.slug, NewsArticle.locale, NewsArticle.updated_at)
        .where(
            NOT_TRASHED,
            NewsArticle.status == ArticleStatus.PUBLISHED,
            NewsArticle.index_in_search.is_(True),
        )
        .order_by(NewsArticle.updated_at.desc())
    )
    return [(slug, locale, updated_at) for slug, locale, updated_at in rows.all()]


_LISTED = (
    NOT_TRASHED,
    NewsArticle.status == ArticleStatus.PUBLISHED,
    NewsArticle.index_in_search.is_(True),
    # The archive's own filter, not a looser one: an article held out of
    # listings does not fill a category page either, so a category whose only
    # article carries it would be advertised as a page that renders nothing.
    NewsArticle.show_in_feed.is_(True),
)
"""What has to be true of an article for a page listing it to be worth indexing."""


async def sitemap_taxonomy_paths(db: AsyncSession) -> list[str]:
    """Every category and tag page that has something to show, per language.

    A taxonomy page is a real, linked, indexable document, so the argument that
    puts the archive index in the sitemap covers the pages that narrow it: a
    crawler told only about the leaves knows the articles exist but not that
    anything links them.

    An *empty* one is not. A category with no published article renders a page
    with nothing on it, and a sitemap is a request to come and index — so the
    set is derived from the articles rather than from the taxonomy tables, and
    a tag stops being advertised when the last article carrying it goes.

    Per language, because the pages are: ``/news/category/x`` and
    ``/de/news/category/x`` list different articles, and either can be empty
    while the other is not.

    Slugs come from the managed rows, which is where a category's or a tag's
    URL is decided. A category name an author typed and never formalised has no
    slug to publish — the archive route accepts the raw name as a fallback, but
    nothing links that address and a sitemap is not the place to invent one.

    Two columns per row, like :func:`sitemap_entries` and for the same reason:
    a join that selected the article entities would drag both block-JSON
    columns through the ORM to answer a question about slugs.
    """
    categories = await db.execute(
        select(NewsCategory.slug, NewsArticle.locale)
        .select_from(NewsArticle)
        .join(NewsCategory, NewsCategory.name == NewsArticle.category)
        .where(*_LISTED)
        .distinct()
        .order_by(NewsCategory.slug, NewsArticle.locale)
    )
    tags = await db.execute(
        select(NewsTag.slug, NewsArticle.locale)
        .select_from(NewsArticle)
        .join(NewsArticleTag, NewsArticleTag.article_id == NewsArticle.id)
        .join(NewsTag, NewsTag.id == NewsArticleTag.tag_id)
        .where(*_LISTED)
        .distinct()
        .order_by(NewsTag.slug, NewsArticle.locale)
    )
    return [
        public_category_path(slug, locale) for slug, locale in categories.all()
    ] + [public_tag_path(slug, locale) for slug, locale in tags.all()]


async def sitemap_author_paths(db: AsyncSession) -> list[str]:
    """Every byline's archive that has something to show, per language.

    Same rule as the taxonomy pages above and for the same reason: an author
    page is a real, linked, indexable document — every article's byline points
    at it — so a crawler should be told it exists, and an empty one is a thin
    page a sitemap has no business inviting anyone to index.

    The slug is derived rather than read off a row, because there is no author
    table; see :mod:`news.authors`. Two consequences show up here. A byline that
    transliterates to nothing has no address and so is simply absent — the
    viewer does not link it either. And two spellings of one byline share an
    address, so the pair is de-duplicated rather than advertised twice.
    """
    rows = await db.execute(
        select(NewsArticle.author, NewsArticle.locale)
        .where(*_LISTED, NewsArticle.author != "")
        .distinct()
        .order_by(NewsArticle.author, NewsArticle.locale)
    )
    seen: set[tuple[str, str]] = set()
    paths: list[str] = []
    for author, locale in rows.all():
        slug = author_slug(author)
        if not slug or (slug, locale) in seen:
            continue
        seen.add((slug, locale))
        paths.append(public_author_path(slug, locale))
    return paths


def sitemap_router() -> APIRouter:
    """The site's one sitemap, mounted under the default language's prefix.

    Under the bare prefix rather than at the app root because it is *news'*
    sitemap: pagebuilder already serves ``/sitemap.xml`` for pages, and two
    modules cannot both own that address. Under the default language's prefix
    rather than each language's because the document it produces is the same
    one, and publishing it at ``/news/sitemap.xml`` and ``/de/news/sitemap.xml``
    would be duplicate content pointing at duplicate content.
    """
    router = APIRouter()

    @router.get("/sitemap.xml", response_model=None)
    async def article_sitemap(
        request: Request, db: AsyncSession = Depends(get_db)
    ) -> Response:
        """Every published article, in every language, for a crawler.

        Articles used to reach one through pagebuilder's sitemap, because they
        were pages in it — see the ``public_claims`` hook that made that work.
        They are not pages any more, so this module advertises its own or the
        archive silently drops out of every index.
        """
        settings = active()
        base = public_base_url(request, settings)
        # The archive's own pages are in it too, one per language. A sitemap
        # listing only the leaves tells a crawler the articles exist but not
        # that anything links them.
        urls = [
            f"<url><loc>{escape(base + public_index_path(locale=locale))}</loc></url>"
            for locale in locales.supported()
        ]
        # And the pages that narrow it — category, tag and byline — where they
        # have something on them. One rule for all three: see
        # ``sitemap_taxonomy_paths``. Before the articles, because that is the
        # order a reader meets them in.
        narrowing = await sitemap_taxonomy_paths(db) + await sitemap_author_paths(db)
        urls += [
            f"<url><loc>{escape(base + path)}</loc></url>" for path in narrowing
        ]
        urls += [
            "<url>"
            f"<loc>{escape(base + public_article_path(slug, locale))}</loc>"
            + (
                f"<lastmod>{updated_at.date().isoformat()}</lastmod>"
                if updated_at
                else ""
            )
            + "</url>"
            for slug, locale, updated_at in await sitemap_entries(db)
        ]
        return Response(
            content=(
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"{''.join(urls)}</urlset>"
            ),
            media_type="application/xml",
            headers={"Cache-Control": cache_control(settings)},
        )

    return router
