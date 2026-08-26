"""News module constants.

Kept out of the call sites so no module name, route or permission appears as a
bare literal — see scripts/check_hardcoded_strings.py.
"""

from __future__ import annotations

from typing import Final

PACKAGE: Final = "news"

ROUTE_PREFIX_API: Final = "/api/news"
# The admin screens sit under /admin, not /news. /news is the *public* address
# an article serves at — see NewsSettings.public_route_prefix — and one prefix
# cannot be both a reader-facing URL and a permission-gated console.
VIEW_PREFIX: Final = "/admin/news"
# Trailing slash: the list route is registered at "/" under VIEW_PREFIX, so
# linking to the bare prefix costs a 307 round trip on every navigation.
MENU_URL: Final = f"{VIEW_PREFIX}/"
MENU_URL_CATEGORIES: Final = f"{VIEW_PREFIX}/categories"
ARTICLE_EDITOR_URL: Final = f"{VIEW_PREFIX}/articles/{{article_id}}/edit"
"""Where an article's metadata is edited. Served to the frontend rather than
assembled there, so the console's own prefix is spelled once."""
ARTICLE_BODY_URL: Final = f"{VIEW_PREFIX}/articles/{{article_id}}/body"
"""Where an article's *body* is composed — news' own block canvas.

This used to be a pagebuilder URL, because the body lived on a page that module
owned. Now it is news', which is what makes the module installable on its own.
"""
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
# articles and — where pagebuilder is installed — pages and media, so filing it
# under the news console would misdescribe what it searches.
ADMIN_SEARCH_PREFIX: Final = "/admin"
ADMIN_SEARCH_URL: Final = f"{ADMIN_SEARCH_PREFIX}/search"
MENU_LABEL_ARTICLES: Final = "Articles"
MENU_LABEL_CATEGORIES: Final = "Categories"

# Inertia page identifiers, rendered as literals at the view so the SM003/SM004
# static-AST diagnostics can pair them with the .tsx under pages/.
_PAGE_LIST: Final = "News/NewsList"
_PAGE_CATEGORIES: Final = "News/Categories"
_PAGE_ARTICLE_EDITOR: Final = "News/ArticleEditor"
_PAGE_ARTICLE_BODY: Final = "News/ArticleBody"
_PAGE_PUBLIC_ARTICLE: Final = "News/PublicArticle"
_PAGE_PUBLIC_INDEX: Final = "News/PublicIndex"
_PAGE_SEARCH: Final = "News/Search"

PERM_VIEW: Final = "news.view"
PERM_EDIT: Final = "news.edit"
PERM_PUBLISH: Final = "news.publish"
"""Separate from ``news.edit`` on purpose.

An article's body used to live on a pagebuilder page, so publishing one went
through *that* module's editor→publisher separation. Owning the content means
owning the separation too: without a permission of its own, every author would
get a way straight past a review step the host may well want.
"""

# Anonymous reads: the feed block runs on public pages, so listing has to work
# without a session. Writes stay behind news.edit.
PUBLIC_READ_PREFIXES: Final = (
    f"{ROUTE_PREFIX_API}/articles",
    f"{ROUTE_PREFIX_API}/categories",
)

# Routes owned by pagebuilder, where a host happens to run it. Spelled here and
# resolved in ``news.integrations.pagebuilder``, which returns "" when the
# module is absent — see that file for why the whole neighbour is optional now.
PAGEBUILDER_EDITOR_PATH: Final = "/pagebuilder/{page_id}/edit"
PAGEBUILDER_MEDIA_PATH: Final = "/pagebuilder/media"
PAGEBUILDER_PAGES_PATH: Final = "/pagebuilder/?view=list&search={query}"

MAX_CATEGORY_LEN: Final = 80
MAX_TAG_LEN: Final = 60
MAX_TITLE_LEN: Final = 300
MAX_AUTHOR_LEN: Final = 120
# Bound on ``NewsArticle.slug``. Derived slugs are cut to it so a long headline
# cannot produce a slug the column rejects.
MAX_SLUG_LEN: Final = 200
# URLs and the meta description share a bound; both are short free text that
# only needs to fit a header or a search result.
MAX_URL_LEN: Final = 500
MAX_NOTE_LEN: Final = 2000
# And the slug's shape. Restated on this module's own DTO so an author who types
# a space into the URL field gets a 422 naming the field, rather than the 500 a
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
