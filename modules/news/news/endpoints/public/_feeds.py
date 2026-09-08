"""What machines read: the sitemap, and the RSS feed.

Both exist for the same reason and neither is optional for an archive. A
sitemap is how the whole archive reaches an index; a feed is how it reaches a
reader who subscribed, an aggregator, and every piece of tooling that has
understood RSS for twenty years. News shipped the first and not the second,
which meant the only way to follow the archive was to keep visiting it.

The two take the language dimension differently, and deliberately:

* **one sitemap** for the site, listing every article in every language at its
  own address. That is how pagebuilder's single ``/sitemap.xml`` works, and a
  crawler wants one document telling it what exists, not one per language it
  has to discover first.
* **one feed per language.** A subscription is a reading habit — a German
  reader who subscribed wants German items, and an English item in that river
  is worse than no item.
"""

from __future__ import annotations

from datetime import datetime
from email.utils import format_datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Request, Response
from simple_module_db import get_db
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from news import locales, service
from news.endpoints.public._urls import (
    absolute,
    cache_control,
    listing_cache_control,
    public_base_url,
)
from news.models import NOT_TRASHED, ArticleStatus, NewsArticle
from news.naive_utc import as_utc
from news.settings import active, public_article_path, public_feed_path, public_index_path

FEED_LIMIT = 20
"""How many articles the feed carries.

A feed is a window on the archive, not a copy of it: a reader subscribing today
wants the recent run, and a reader who wants everything has the sitemap.
"""


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


def feed_router(locale: str) -> APIRouter:
    """The recent archive in one language, as RSS 2.0."""
    router = APIRouter()

    @router.get("/feed.xml", response_model=None)
    async def article_feed(
        request: Request, db: AsyncSession = Depends(get_db)
    ) -> Response:
        """The recent archive, as RSS 2.0.

        RSS rather than Atom because it is what every reader and aggregator
        accepts without argument, and the address is ``feed.xml`` rather than
        ``rss.xml`` so that choice can be revisited without breaking a
        subscription.

        Items carry the excerpt, not the body. The body is a block document, and
        rendering twenty-one React components to HTML server-side is a different
        project — a feed that says what an article is and links to it is the
        useful ninety per cent, and a truncated-looking body would be the
        annoying one.
        """
        settings = active()
        base = public_base_url(request, settings)
        # `with_total=False` because a feed has no pager: it is a fixed window,
        # and the `count(*)` behind it would be a second scan of the whole
        # archive for a number nothing here reads.
        items, _ = await service.list_articles(
            db, limit=FEED_LIMIT, in_feed_only=True, locale=locale, with_total=False
        )

        entries = []
        for item in items:
            url = base + item.url
            # `format_datetime` treats a naive value as local time, which would
            # misdate the item for any reader whose host isn't running in UTC.
            pub_dt = as_utc(item.published_at)
            published = (
                f"<pubDate>{format_datetime(pub_dt)}</pubDate>"
                if pub_dt is not None
                else ""
            )
            entries.append(
                "<item>"
                f"<title>{escape(item.title)}</title>"
                f"<link>{escape(url)}</link>"
                # The article's own address is its identity — permanent, unlike
                # the title, and already what a redirect keeps working after a
                # rename.
                f'<guid isPermaLink="true">{escape(url)}</guid>'
                + (
                    f"<description>{escape(item.excerpt)}</description>"
                    if item.excerpt
                    else ""
                )
                + (
                    f"<category>{escape(item.category)}</category>"
                    if item.category
                    else ""
                )
                + published
                + "</item>"
            )

        title = settings.site_name or "News"
        index_url = absolute(request, settings, public_index_path(locale=locale))
        self_url = absolute(request, settings, public_feed_path(locale))
        return Response(
            content=(
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">'
                "<channel>"
                f"<title>{escape(title)}</title>"
                f"<link>{escape(index_url)}</link>"
                f"<description>{escape(title)}</description>"
                # Which language this river is in, so a reader that aggregates
                # several of a site's feeds can tell them apart.
                f"<language>{escape(locale)}</language>"
                f'<atom:link href="{escape(self_url)}"'
                ' rel="self" type="application/rss+xml"/>'
                f"{''.join(entries)}"
                "</channel></rss>"
            ),
            media_type="application/rss+xml",
            headers={"Cache-Control": listing_cache_control(settings)},
        )

    return router
