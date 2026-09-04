"""News module constants.

Kept out of the call sites so no module name, route or permission appears as a
bare literal — see scripts/check_hardcoded_strings.py.
"""

from __future__ import annotations

from typing import Final

PACKAGE: Final = "news"

ROUTE_PREFIX_API: Final = "/api/news"
# The admin screens sit under /admin, not /news. /news is the *public* address
# an article serves at now — see NewsSettings.public_route_prefix — and one
# prefix cannot be both a reader-facing URL and a permission-gated console.
# The search screen was already at /admin/search for its own reasons; this puts
# the rest of the module's console beside it.
VIEW_PREFIX: Final = "/admin/news"
# Trailing slash: the list route is registered at "/" under VIEW_PREFIX, so
# linking to the bare prefix costs a 307 round trip on every navigation.
MENU_URL: Final = f"{VIEW_PREFIX}/"
MENU_URL_CATEGORIES: Final = f"{VIEW_PREFIX}/categories"
ARTICLE_EDITOR_URL: Final = f"{VIEW_PREFIX}/articles/{{article_id}}/edit"
"""Where an article's metadata is edited. Served to the frontend rather than
assembled there, so the console's own prefix is spelled once."""
# The rail splits by section rather than lumping every content surface into
# one "Content" group: which module a screen belongs to is then legible from
# the sidebar as well as from the URL.
MENU_GROUP: Final = "News"
MENU_ICON: Final = "newspaper"
MENU_ICON_CATEGORIES: Final = "tags"
MENU_ICON_SEARCH: Final = "search"
MENU_LABEL_SEARCH: Final = "Search everything"
MENU_GROUP_SEARCH: Final = "Find"

# Mounted at the app root rather than under VIEW_PREFIX: the screen spans
# articles, pages and media, so filing it under the news console would
# misdescribe what it searches.
ADMIN_SEARCH_PREFIX: Final = "/admin"
ADMIN_SEARCH_URL: Final = f"{ADMIN_SEARCH_PREFIX}/search"
MENU_LABEL_ARTICLES: Final = "Articles"
MENU_LABEL_CATEGORIES: Final = "Categories"

# Modules this one depends on.
_MODULE_PAGEBUILDER: Final = "PageBuilder"
#: The framework's settings module, by ``ModuleMeta.name``. Depended on so the
#: host has built ``app.state.settings.module_registry`` before this module's
#: ``register_settings`` tries to register against it.
_MODULE_SETTINGS: Final = "Settings"

# Inertia page identifier, rendered as a literal at the view so the SM003/SM004
# static-AST diagnostics can pair it with pages/NewsList.tsx.
_PAGE_LIST: Final = "News/NewsList"
_PAGE_CATEGORIES: Final = "News/Categories"
_PAGE_ARTICLE_EDITOR: Final = "News/ArticleEditor"
_PAGE_SEARCH: Final = "News/Search"

PERM_VIEW: Final = "news.view"
PERM_EDIT: Final = "news.edit"

# Anonymous reads: the feed block runs on public pages, so listing has to work
# without a session. Writes stay behind news.edit.
PUBLIC_READ_PREFIXES: Final = (
    f"{ROUTE_PREFIX_API}/articles",
    f"{ROUTE_PREFIX_API}/categories",
)

# Routes owned by pagebuilder. Spelled here, resolved in
# ``news.integrations.pagebuilder``, so no other module in news — and nothing
# in its frontend — has to know how the neighbour routes its own screens.
PAGEBUILDER_EDITOR_PATH: Final = "/pagebuilder/{page_id}/edit"
PAGEBUILDER_MEDIA_PATH: Final = "/pagebuilder/media"
PAGEBUILDER_PAGES_PATH: Final = "/pagebuilder/?view=list&search={query}"

MAX_CATEGORY_LEN: Final = 80
# Pagebuilder's bound on ``Page.locale``. Restated here for the same reason
# MAX_SLUG_LEN is: a DTO that accepted more would 500 inside the page write
# instead of 422ing on the field the author filled in.
MAX_LOCALE_LEN: Final = 12
MAX_TAG_LEN: Final = 60
MAX_TITLE_LEN: Final = 300
# Pagebuilder's own bound on ``Page.slug``. Derived slugs are cut to it here so
# a long headline cannot produce a slug the column rejects.
MAX_SLUG_LEN: Final = 200
# And its shape. Restated on this module's own DTO so an author who types a
# space into the URL field gets a 422 naming the field, rather than the 500 a
# ValidationError raised from inside the handler produces.
SLUG_PATTERN: Final = r"^[a-z0-9][a-z0-9-]*$"
# How many ``-2``, ``-3``… variants to try before giving up on deriving a slug
# and asking the author for one. Far past any honest collision; it exists so a
# pathological title cannot spin.
MAX_SLUG_ATTEMPTS: Final = 20

# The feed block runs on every public page carrying one, so an uncacheable
# listing costs a database round trip per page view. Short enough that a newly
# published article appears within a minute.
PUBLIC_CACHE_SECONDS: Final = 60
PUBLIC_CACHE_CONTROL: Final = f"public, max-age={PUBLIC_CACHE_SECONDS}"
# An editor's listing includes drafts, so it differs by permission and must
# never be held anywhere another visitor could be served it from.
PRIVATE_CACHE_CONTROL: Final = "private, no-store"
# Shown on the categories screen as the system row. Articles in it carry an
# empty ``category``; there is no table row, so it cannot be renamed or
# deleted — which is exactly what the screen promises.
UNCATEGORISED_LABEL: Final = "Uncategorised"
DEFAULT_LIMIT: Final = 20
MAX_LIMIT: Final = 100
