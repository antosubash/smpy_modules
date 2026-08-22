"""The single place news knows what pagebuilder *is*.

An article is a pagebuilder page, so some coupling is the design rather than an
accident. What is avoidable is the coupling being *spread*. Before this module
existed the neighbour's package was imported by eight modules here — the
listing, the counts, the taxonomy, the search, the repair sweep, the query
fragments, the contracts and the module registration — its ``PageStatus`` was
re-exported as part of news' own public DTO, and its CSRF cookie name, page API
route and editor URL were hardcoded in the frontend. Every one of those had to
be right for a framework bump to be safe.

Now the borrowing is declared once, in news' own vocabulary:

* the page and media tables the listings join to, and the visibility predicate
  that keeps a trashed page out of them,
* the ``PageDeleted`` event the orphan sweep hangs off,
* the service that creates and publishes the page an article's body lives in,
* the admin routes a link has to point at.

Two siblings carry the rest of the borrowing, because this file is at the
repo's 300-line cap: :mod:`news.integrations.pages` holds the *writes* news
performs on a page (create, translate, publish) and
:mod:`news.integrations.locales` the site's content languages.

Nothing outside this package imports ``pagebuilder``. The rule is worth keeping
even where a re-export looks redundant, because it is what makes ``requires``
in ``pyproject.toml`` checkable by reading one file.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import Request, Response
from pagebuilder import public_claims, redirects
from pagebuilder.contracts.events import PageDeleted
from pagebuilder.deps import get_settings as pagebuilder_settings
from pagebuilder.endpoints.api._deps import require_edit as require_page_edit
from pagebuilder.endpoints.api._deps import require_publish as require_page_publish
from pagebuilder.endpoints.public_views import render_public_page
from pagebuilder.models import NOT_TRASHED, MediaAsset, Page, PageStatus
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Load

from news.constants import (
    PAGEBUILDER_EDITOR_PATH,
    PAGEBUILDER_MEDIA_PATH,
    PAGEBUILDER_PAGES_PATH,
)
from news.contracts.schemas import ArticleStatus

__all__ = [
    "NOT_TRASHED",
    "MediaAsset",
    "Page",
    "PageDeleted",
    "PageStatus",
    "article_status",
    "card_columns",
    "claim_slugs",
    "media_library_path",
    "page_editor_path",
    "page_search_path",
    "redirected_slug",
    "render_article_page",
    "require_page_edit",
    "require_page_publish",
]


# Re-exported so a news route can demand the same authority pagebuilder does
# for the same write. Pagebuilder separates editor from publisher on purpose —
# "let hosts run the editor → publisher workflow without granting every editor
# publish rights" — and news creating and publishing pages under ``news.edit``
# alone would hand every article author a way straight past that separation.
# The article routes require both: news' own permission, and the neighbour's
# for the page write they perform on its behalf.


def page_editor_path(page_id: int) -> str:
    """Where an author edits the body.

    Served to the frontend rather than assembled there, so the admin list holds
    no opinion about how another module routes its editor.
    """
    return PAGEBUILDER_EDITOR_PATH.format(page_id=page_id)


def media_library_path() -> str:
    return PAGEBUILDER_MEDIA_PATH


def page_search_path(query: str) -> str:
    """Pagebuilder's own page list, pre-filtered — the "see all" of a search.

    The query is percent-encoded because it goes into a query *value*: a search
    for ``R&D`` would otherwise arrive as ``search=R`` plus a stray parameter,
    and one containing ``#`` would truncate the URL at the fragment and land on
    an unfiltered list.
    """
    return PAGEBUILDER_PAGES_PATH.format(query=quote(query, safe=""))


def article_status(status: PageStatus) -> ArticleStatus:
    """Map the page's workflow state onto news' own enum.

    Same string values, so the wire format is unchanged — the point is that
    ``ArticleRead`` no longer re-exports another module's enum as part of news'
    public contract.
    """
    return ArticleStatus(status.value)


def card_columns() -> Load:
    """The only Page columns a news card reads.

    Without this the listing join dragged both block-JSON columns through the
    ORM for every row, so list cost scaled with page *content* size instead of
    card count (issue #12). Anything outside this set raises on access —
    loudly, in tests — rather than silently re-widening the query.

    ``status`` is in the set because the serializer reads it; leaving it out
    lazy-loads on access, which raises MissingGreenlet under the async session
    (issue #20).
    """
    return Load(Page).load_only(
        Page.slug,
        Page.title,
        Page.meta_description,
        Page.og_image,
        Page.status,
        # The card's public URL is locale-prefixed and its language switcher
        # keys off the group, so both are read on every row. Left out, they
        # lazy-load on access — which under the async session raises
        # MissingGreenlet rather than working (issue #20 again).
        Page.locale,
        Page.translation_group,
    )


def claim_slugs(claim: public_claims.SlugClaim) -> None:
    """Tell pagebuilder these slugs serve at news' address, not its own.

    Registered at startup. Two things follow from it, both pagebuilder's doing:
    ``/p/{slug}`` 404s for an article, and the sitemap advertises the news URL
    instead of one the viewer would refuse.
    """
    public_claims.register(claim)


async def render_article_page(
    slug: str,
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession,
    *,
    url_prefix: str,
    locale: str | None = None,
) -> Response:
    """Serve an article's body through pagebuilder's own public viewer.

    News owns the *address*; it does not own page rendering. Reusing the viewer
    is what keeps the ETag, cache headers, CSP, canonical tag, site layout and
    old-slug redirects identical to every other published page — a second
    viewer would start equal and drift.

    ``url_prefix`` is news', so the canonical tag names the address the article
    actually serves at rather than the one it no longer answers on. ``locale``
    is which language's article to serve; the viewer builds the canonical tag
    and the ``hreflang`` alternates from news' prefix and that language, so a
    translated article advertises ``/de/news/…`` rather than ``/de/p/…``.
    """
    return await render_public_page(
        slug,
        request,
        inertia,
        db,
        pagebuilder_settings(request),
        url_prefix=url_prefix,
        locale=locale,
    )


async def redirected_slug(db: AsyncSession, slug: str, locale: str) -> str | None:
    """The slug an old address now points at *within ``locale``*, or ``None``.

    A rename is not a private edit — the old URL is in bookmarks, in links from
    other sites and in a search index that has not recrawled — so pagebuilder
    records one. News reads the same table rather than keeping its own, which
    is what makes renaming an article behave like renaming any other page.
    """
    return await redirects.resolve(db, slug, locale)
