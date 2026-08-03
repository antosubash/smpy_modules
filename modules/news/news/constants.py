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
DEFAULT_LIMIT: Final = 20
MAX_LIMIT: Final = 100
