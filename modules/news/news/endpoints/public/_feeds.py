"""The RSS feed: how the archive reaches a reader who subscribed.

A feed is not optional for an archive. News shipped a sitemap and no feed for a
while, which meant the only way to follow it was to keep visiting it — an
aggregator, a reader app and twenty years of tooling all understand RSS, and
none of them understand "check back".

**One feed per language**, unlike the single sitemap next door. A subscription
is a reading habit: a German reader who subscribed wants German items, and an
English item in that river is worse than no item.
"""

from __future__ import annotations

from email.utils import format_datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Request, Response
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from news import service
from news.endpoints.public._urls import (
    absolute,
    listing_cache_control,
    public_base_url,
)
from news.naive_utc import as_utc
from news.settings import active, public_feed_path, public_index_path

FEED_LIMIT = 20
"""How many articles the feed carries.

A feed is a window on the archive, not a copy of it: a reader subscribing today
wants the recent run, and a reader who wants everything has the sitemap.
"""


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
