"""Everything news serves to an anonymous reader.

Split by surface — the archive pages, the feeds, one article — because the
article viewer alone had already filled a file, and the front door added four
more routes to it.

**Registration order here is load-bearing.** FastAPI matches routes in the order
they are added, and ``/{slug}`` matches any single segment: registered first it
would swallow ``feed.xml`` and ``sitemap.xml`` and answer 404 for both. The
article router therefore goes last, and every fixed path goes before it. This
has already been a bug once, when ``sitemap.xml`` was added below the catch-all.
"""

from __future__ import annotations

from fastapi import APIRouter

from news.endpoints.public._article import article_router
from news.endpoints.public._feeds import feed_router, sitemap_entries
from news.endpoints.public._index import index_router

public_router = APIRouter()
# Fixed paths first...
public_router.include_router(feed_router)
public_router.include_router(index_router)
# ...and the catch-all last.
public_router.include_router(article_router)

__all__ = ["public_router", "sitemap_entries"]
