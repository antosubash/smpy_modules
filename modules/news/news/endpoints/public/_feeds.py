"""What machines read: the sitemap, and the RSS feed.

Both exist for the same reason and neither is optional for an archive. A
sitemap is how the whole archive reaches an index; a feed is how it reaches a
reader who subscribed, an aggregator, and every piece of tooling that has
understood RSS for twenty years. News shipped the first and not the second,
which meant the only way to follow the archive was to keep visiting it.
"""

from __future__ import annotations

from datetime import datetime
from email.utils import format_datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Request, Response
from simple_module_db import get_db
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from news import service
from news.endpoints.public._urls import (
    absolute,
    cache_control,
    listing_cache_control,
    public_base_url,
)
from news.models import NOT_TRASHED, ArticleStatus, NewsArticle
from news.settings import active, public_article_path, public_feed_path, public_index_path

feed_router = APIRouter()

FEED_LIMIT = 20
"""How many articles the feed carries.

A feed is a window on the archive, not a copy of it: a reader subscribing today
wants the recent run, and a reader who wants everything has the sitemap.
"""


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


@feed_router.get("/sitemap.xml", response_model=None)
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
    base = public_base_url(request, settings)
    # The archive's own pages are in it too. A sitemap listing only the leaves
    # tells a crawler the articles exist but not that anything links them.
    urls = [f"<url><loc>{escape(base + public_index_path())}</loc></url>"]
    urls += [
        "<url>"
        f"<loc>{escape(base + public_article_path(slug))}</loc>"
        + (f"<lastmod>{updated_at.date().isoformat()}</lastmod>" if updated_at else "")
        + "</url>"
        for slug, updated_at in await sitemap_entries(db)
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


@feed_router.get("/feed.xml", response_model=None)
async def article_feed(
    request: Request, db: AsyncSession = Depends(get_db)
) -> Response:
    """The recent archive, as RSS 2.0.

    RSS rather than Atom because it is what every reader and aggregator accepts
    without argument, and the address is ``feed.xml`` rather than ``rss.xml`` so
    that choice can be revisited without breaking a subscription.

    Items carry the excerpt, not the body. The body is a block document, and
    rendering twenty-one React components to HTML server-side is a different
    project — a feed that says what an article is and links to it is the useful
    ninety per cent, and a truncated-looking body would be the annoying one.
    """
    settings = active()
    base = public_base_url(request, settings)
    # `with_total=False` because a feed has no pager: it is a fixed window, and
    # the `count(*)` behind it would be a second scan of the whole archive for
    # a number nothing here reads.
    items, _ = await service.list_articles(
        db, limit=FEED_LIMIT, in_feed_only=True, with_total=False
    )

    entries = []
    for item in items:
        url = base + item.url
        published = (
            f"<pubDate>{format_datetime(item.published_at)}</pubDate>"
            if item.published_at is not None
            else ""
        )
        entries.append(
            "<item>"
            f"<title>{escape(item.title)}</title>"
            f"<link>{escape(url)}</link>"
            # The article's own address is its identity — permanent, unlike the
            # title, and already what a redirect keeps working after a rename.
            f'<guid isPermaLink="true">{escape(url)}</guid>'
            + (f"<description>{escape(item.excerpt)}</description>" if item.excerpt else "")
            + (f"<category>{escape(item.category)}</category>" if item.category else "")
            + published
            + "</item>"
        )

    title = settings.site_name or "News"
    return Response(
        content=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">'
            "<channel>"
            f"<title>{escape(title)}</title>"
            f"<link>{escape(absolute(request, settings, public_index_path()))}</link>"
            f"<description>{escape(title)}</description>"
            f'<atom:link href="{escape(absolute(request, settings, public_feed_path()))}"'
            ' rel="self" type="application/rss+xml"/>'
            f"{''.join(entries)}"
            "</channel></rss>"
        ),
        media_type="application/rss+xml",
        headers={"Cache-Control": listing_cache_control(settings)},
    )
