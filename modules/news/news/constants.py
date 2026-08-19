"""News module constants.

Kept out of the call sites so no module name, route or permission appears as a
bare literal — see scripts/check_hardcoded_strings.py.
"""

from __future__ import annotations

from typing import Final

PACKAGE: Final = "news"

ROUTE_PREFIX_API: Final = "/api/news"
VIEW_PREFIX: Final = "/news"
# Trailing slash: the list route is registered at "/" under VIEW_PREFIX, so
# linking to the bare prefix costs a 307 round trip on every navigation.
MENU_URL: Final = f"{VIEW_PREFIX}/"
MENU_GROUP: Final = "Content"
MENU_ICON: Final = "newspaper"

# Modules this one depends on.
_MODULE_PAGEBUILDER: Final = "PageBuilder"

# Inertia page identifier, rendered as a literal at the view so the SM003/SM004
# static-AST diagnostics can pair it with pages/NewsList.tsx.
_PAGE_LIST: Final = "News/NewsList"

PERM_VIEW: Final = "news.view"
PERM_EDIT: Final = "news.edit"

# Anonymous reads: the feed block runs on public pages, so listing has to work
# without a session. Writes stay behind news.edit.
PUBLIC_READ_PREFIXES: Final = (
    f"{ROUTE_PREFIX_API}/articles",
    f"{ROUTE_PREFIX_API}/categories",
)

MAX_CATEGORY_LEN: Final = 80
# Matches pagebuilder's own Page.title bound; a longer title would be rejected
# by the page create this module makes on the author's behalf, and a 422 naming
# a neighbour's field is not a useful thing to show an author.
MAX_TITLE_LEN: Final = 300
DEFAULT_LIMIT: Final = 20
MAX_LIMIT: Final = 100

# Slugs for pages created from "New article".
MAX_SLUG_LEN: Final = 200
# How far "my-title-2", "-3"… is tried before falling back to a suffix that
# cannot collide. Purely a bound on the loop; a site with 20 identically
# titled articles has a naming problem this cannot fix.
MAX_SLUG_ATTEMPTS: Final = 20

# Anonymous listing responses are cacheable: the feed block runs on every
# public page that carries it, so without this each such page view costs an
# uncached database round trip. Short, because a published article should
# reach the site promptly rather than after a long TTL.
PUBLIC_CACHE_SECONDS: Final = 60
PUBLIC_CACHE_CONTROL: Final = f"public, max-age={PUBLIC_CACHE_SECONDS}"
# An editor's listing includes drafts, so it is specific to that person and
# must never be held by a shared cache.
PRIVATE_CACHE_CONTROL: Final = "private, no-store"

# Query value asking for the articles that have no category at all. A blank
# string cannot carry that meaning — the listing reads it as "no category
# filter" — so the two states need distinct spellings on the wire.
UNCATEGORISED: Final = "__none__"
