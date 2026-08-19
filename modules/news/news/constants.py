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
MENU_URL_CATEGORIES: Final = f"{VIEW_PREFIX}/categories"
# The rail splits by section rather than lumping every content surface into
# one "Content" group: which module a screen belongs to is then legible from
# the sidebar as well as from the URL.
MENU_GROUP: Final = "News"
MENU_ICON: Final = "newspaper"
MENU_ICON_CATEGORIES: Final = "tags"
MENU_LABEL_ARTICLES: Final = "Articles"
MENU_LABEL_CATEGORIES: Final = "Categories"

# Modules this one depends on.
_MODULE_PAGEBUILDER: Final = "PageBuilder"

# Inertia page identifier, rendered as a literal at the view so the SM003/SM004
# static-AST diagnostics can pair it with pages/NewsList.tsx.
_PAGE_LIST: Final = "News/NewsList"
_PAGE_CATEGORIES: Final = "News/Categories"

PERM_VIEW: Final = "news.view"
PERM_EDIT: Final = "news.edit"

# Anonymous reads: the feed block runs on public pages, so listing has to work
# without a session. Writes stay behind news.edit.
PUBLIC_READ_PREFIXES: Final = (
    f"{ROUTE_PREFIX_API}/articles",
    f"{ROUTE_PREFIX_API}/categories",
)

MAX_CATEGORY_LEN: Final = 80
MAX_TAG_LEN: Final = 60
# Shown on the categories screen as the system row. Articles in it carry an
# empty ``category``; there is no table row, so it cannot be renamed or
# deleted — which is exactly what the screen promises.
UNCATEGORISED_LABEL: Final = "Uncategorised"
DEFAULT_LIMIT: Final = 20
MAX_LIMIT: Final = 100
