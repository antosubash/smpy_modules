"""The single place news knows pagebuilder *might* be there.

An article used to *be* a pagebuilder page. The body, the slug, the workflow,
the revisions and the public rendering all lived in that module, so news could
not boot without it: eight modules here imported its package, its ``PageStatus``
was re-exported through news' own DTO, and its CSRF cookie name and editor URL
were hardcoded in the frontend.

None of that is true any more. ``NewsArticle`` carries its own body, address,
status and revisions, and :mod:`news.endpoints.public` serves them. What
remains is genuinely optional — conveniences that only make sense on a
site that happens to run both modules:

* the admin search screen searches *pages* and *media* alongside articles,
  because on such a site those are things an editor is looking for;
* the "see all" links on those two sections point into pagebuilder's own
  screens;
* the site's content languages are pagebuilder's, borrowed through the sibling
  :mod:`news.integrations.locales` — a separate file because it answers a
  question about configuration rather than about data, behind the same
  boundary;
* articles travel in pagebuilder's content bundle (Import / Export and the
  ``pre_restore`` snapshot) as a contributed section, :mod:`news.integrations.bundle`,
  registered by :func:`register_bundle_section` (#80).

So every import here is deferred and guarded. On a host without pagebuilder
``available()`` is ``False``, the two extra sections return nothing, news
publishes in one language, and every other part of this module carries on
unaffected — which is the whole point of the split.
"""

from __future__ import annotations

import logging
from functools import cache
from typing import Any
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession

from news.constants import (
    PAGEBUILDER_EDITOR_PATH,
    PAGEBUILDER_MEDIA_PATH,
    PAGEBUILDER_PAGES_PATH,
)
from news.tenancy import search_tenant

logger = logging.getLogger(__name__)

__all__ = [
    "available",
    "media_library_path",
    "page_editor_path",
    "page_search_path",
    "register_bundle_section",
    "render_not_found",
    "search_media",
    "search_pages",
]


@cache
def available() -> bool:
    """Whether ``simple_module_pagebuilder`` is installed in this host.

    Cached because it is asked once per search request and the answer cannot
    change inside a process — a package does not appear mid-run. ``cache``
    rather than a module-level constant so importing news never imports
    pagebuilder as a side effect; the question is only asked when something
    actually needs the answer.
    """
    try:
        import pagebuilder  # noqa: F401
    except ImportError:
        return False
    return True


def _contract() -> Any:
    """Pagebuilder's public search contract, or ``None``.

    :mod:`pagebuilder.contracts` and nothing deeper: its tables, status enum and
    tenant column are its own to change (#130). Imported inside the call rather
    than at module scope: at module scope an ImportError here would take news
    down on a host that simply chose not to install the neighbour.
    """
    if not available():
        return None
    from pagebuilder import contracts

    return contracts


# ── Links into pagebuilder's own screens ──────────────────────────────
# All three return "" when it is absent. The frontend renders a section's
# "see all" only when it has somewhere to send you, so an empty string is a
# missing affordance rather than a broken link.


def page_editor_path(page_id: int) -> str:
    return PAGEBUILDER_EDITOR_PATH.format(page_id=page_id) if available() else ""


def media_library_path() -> str:
    return PAGEBUILDER_MEDIA_PATH if available() else ""


def page_search_path(query: str) -> str:
    """Pagebuilder's own page list, pre-filtered — the "see all" of a search.

    The query is percent-encoded because it goes into a query *value*: a search
    for ``R&D`` would otherwise arrive as ``search=R`` plus a stray parameter,
    and one containing ``#`` would truncate the URL at the fragment and land on
    an unfiltered list.
    """
    if not available():
        return ""
    return PAGEBUILDER_PAGES_PATH.format(query=quote(query, safe=""))


# ── The two optional search sections ──────────────────────────────────


async def search_pages(
    db: AsyncSession, pattern: str, *, include_drafts: bool, limit: int
) -> tuple[list[Any], int]:
    """Pages matching ``pattern``, newest first, and how many there are.

    ``([], 0)`` when pagebuilder is not installed — the search screen then shows
    no Pages section at all, which is honest: there are no pages.

    Articles are no longer pages, so nothing has to be excluded from this the
    way it once did. The two sections cannot double-count because they are two
    different tables. The tenant is news' to choose (:func:`search_tenant`);
    pinning it, and everything else about the query, is pagebuilder's.
    """
    contract = _contract()
    if contract is None:
        return [], 0
    return await contract.search_pages(
        db, pattern, tenant_id=search_tenant(), include_drafts=include_drafts, limit=limit
    )


async def search_media(db: AsyncSession, pattern: str, *, limit: int) -> tuple[list[Any], int]:
    """Media assets matching ``pattern``. ``([], 0)`` without pagebuilder."""
    contract = _contract()
    if contract is None:
        return [], 0
    return await contract.search_media(db, pattern, tenant_id=search_tenant(), limit=limit)


# ── The site's not-found page ─────────────────────────────────────────


async def render_not_found(
    request: Any,
    inertia: Any,
    db: AsyncSession,
    *,
    locale: str,
    tenant_id: str | None,
    detail: str,
) -> Any:
    """The site's branded 404 (#248), or ``None`` without pagebuilder.

    ``None`` too where pagebuilder is installed but not mounted on this app, or
    is older than the contract: there is no site frame to put the page in, and
    the caller answers with its own plain 404.
    """
    public = getattr(_contract(), "public", None)
    if public is None:
        return None
    return await public.render_not_found(
        request, inertia, db, locale=locale, tenant_id=tenant_id, detail=detail
    )


# ── The content bundle ────────────────────────────────────────────────


def register_bundle_section(app: Any) -> bool:
    """Make articles part of pagebuilder's content bundle, where it is mounted (#80).

    ``False`` and nothing else when pagebuilder is not installed, or installed
    but not mounted on this app. Both imports are deferred: ``news.integrations.bundle``
    imports :mod:`pagebuilder.contracts` at module scope, so importing it is
    what would make the neighbour a hard requirement. Pagebuilder creates its
    section registry while the app is built, before any ``on_startup``, so
    the order the two modules start in does not matter.
    """
    if not available():
        return False
    try:
        from pagebuilder.contracts import bundle
    except ImportError:  # a pagebuilder older than the extra's floor: no bundle contract
        return False

    from news.integrations.bundle import NewsBundleSection

    return bundle.register_section(app, NewsBundleSection())
