"""Everything news serves to an anonymous reader.

Split by surface — the archive pages, the feeds, one article — because the
article viewer alone had already filled a file, and the front door added four
more routes to it.

**One router per content locale.** The site's default language keeps the bare
prefix (``/news/…``) so no address that already exists changes, and every other
language is prefixed with its tag (``/de/news/…``), mirroring how pagebuilder
addresses pages. A router each rather than a ``/{locale}`` path parameter: a
parameter matches *any* first segment, and the public-route registry exempts by
string prefix, so the exemption would have to be widened to something that no
longer describes what is public.

**Registration order inside one is load-bearing.** FastAPI matches routes in the
order they are added, and ``/{slug}`` matches any single segment: registered
first it would swallow ``feed.xml`` and ``sitemap.xml`` and answer 404 for both.
The article router therefore goes last, and every fixed path goes before it.
This has already been a bug once, when ``sitemap.xml`` was added below the
catch-all.
"""

from __future__ import annotations

from fastapi import APIRouter

from news import locales
from news.endpoints.public._article import article_router, default_locale_alias_router
from news.endpoints.public._feeds import feed_router, sitemap_entries, sitemap_router
from news.endpoints.public._index import index_router


def public_router(locale: str) -> APIRouter:
    """Everything one language serves, ready to mount under its own prefix."""
    router = APIRouter()
    # Fixed paths first...
    router.include_router(feed_router(locale))
    if locales.is_default(locale):
        # One sitemap for the whole site, listing every language at its own
        # address — see ``sitemap_router``. It hangs off the default language's
        # prefix because that is the address that exists on every site,
        # monolingual or not.
        router.include_router(sitemap_router())
    router.include_router(index_router(locale))
    # ...and the catch-all last.
    router.include_router(article_router(locale))
    return router


__all__ = [
    "default_locale_alias_router",
    "public_router",
    "sitemap_entries",
]
