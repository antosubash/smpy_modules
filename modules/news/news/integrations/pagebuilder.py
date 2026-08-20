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

Nothing outside this package imports ``pagebuilder``. The rule is worth keeping
even where a re-export looks redundant, because it is what makes ``requires``
in ``pyproject.toml`` checkable by reading one file.
"""

from __future__ import annotations

from fastapi import HTTPException
from pagebuilder.contracts.events import PageDeleted
from pagebuilder.contracts.schemas import PageCreate
from pagebuilder.models import NOT_TRASHED, MediaAsset, Page, PageStatus
from pagebuilder.service import PagesService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Load

from news.constants import (
    MAX_SLUG_ATTEMPTS,
    MAX_SLUG_LEN,
    PAGEBUILDER_EDITOR_PATH,
    PAGEBUILDER_MEDIA_PATH,
    PAGEBUILDER_PAGES_PATH,
)
from news.contracts.schemas import ArticleStatus
from news.slugify import slugify

__all__ = [
    "NOT_TRASHED",
    "MediaAsset",
    "Page",
    "PageDeleted",
    "PageStatus",
    "article_status",
    "card_columns",
    "create_article_page",
    "empty_puck_document",
    "media_library_path",
    "page_editor_path",
    "page_search_path",
    "publish_page",
    "slug_for_title",
]


def page_editor_path(page_id: int) -> str:
    """Where an author edits the body.

    Served to the frontend rather than assembled there, so the admin list holds
    no opinion about how another module routes its editor.
    """
    return PAGEBUILDER_EDITOR_PATH.format(page_id=page_id)


def media_library_path() -> str:
    return PAGEBUILDER_MEDIA_PATH


def page_search_path(query: str) -> str:
    """Pagebuilder's own page list, pre-filtered — the "see all" of a search."""
    return PAGEBUILDER_PAGES_PATH.format(query=query)


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
    )


def empty_puck_document(title: str) -> dict:
    """What pagebuilder's editor expects to open for a page with no body yet.

    The title is repeated into the root props because that is where the editor
    reads the document heading from; the ``Page.title`` column drives the admin
    list and the public ``<title>``.
    """
    return {
        "root": {"props": {"title": title, "width": "full"}},
        "content": [],
        "zones": {},
    }


def slug_for_title(title: str) -> str:
    """News' own slug rule, bounded by pagebuilder's ``slug`` column.

    ``news.slugify`` already produces something ``PageCreate``'s
    ``^[a-z0-9][a-z0-9-]*$`` accepts — it trims again after truncating, so the
    cut cannot leave a trailing hyphen — and falls back rather than returning an
    empty string. Both matter here: a slug that fails that pattern is a 422 the
    author has no way to act on.
    """
    return slugify(title, max_length=MAX_SLUG_LEN)


async def _free_slug(db: AsyncSession, base: str) -> str:
    """``base``, or ``base-2``, ``base-3``… — the first nobody is using.

    One query rather than one per candidate: the alternative is a
    create-and-catch-409 loop, and ``PagesService.create`` rolls the session
    back on conflict, which would discard anything the caller had already
    written in the same transaction.

    Returns ``""`` when even the suffixed candidates are all taken, which the
    caller turns into an error rather than guessing further.
    """
    taken = set(
        (
            await db.execute(select(Page.slug).where(Page.slug.startswith(base)))
        ).scalars()
    )
    if base not in taken:
        return base
    for suffix in range(2, MAX_SLUG_ATTEMPTS + 2):
        candidate = f"{base[: MAX_SLUG_LEN - len(str(suffix)) - 1]}-{suffix}"
        if candidate not in taken:
            return candidate
    return ""


async def create_article_page(
    db: AsyncSession, *, title: str, slug: str | None = None
) -> Page:
    """Create the page an article's body will live in.

    This runs on the server so that creating an article is one request under
    news' own CSRF token. The frontend used to POST to pagebuilder's page API
    directly, which meant knowing pagebuilder's cookie name and priming it with
    a throwaway GET — and left an orphaned, empty page behind whenever the
    second call failed, because the two writes were in different transactions.

    An author-supplied ``slug`` is used verbatim, and a collision is reported
    rather than silently altered: the URL is a thing they typed and expect to
    get. Only the derived default looks for a free variant, because there the
    author expressed no preference beyond the headline.
    """
    if slug:
        chosen = slug
    else:
        chosen = await _free_slug(db, slug_for_title(title))
        if not chosen:
            raise _slug_exhausted(title)
    return await PagesService(db).create(
        PageCreate(title=title, slug=chosen, draft_data=empty_puck_document(title))
    )


def _slug_exhausted(title: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=f"Could not derive a free URL from {title!r}. Set one explicitly.",
    )


async def publish_page(db: AsyncSession, page_id: int) -> Page:
    """Publish the page behind an article.

    Here rather than in the browser for the same reason as ``create``: the row
    menu's Publish used to POST to pagebuilder's API with a borrowed CSRF token,
    which is the last thing that made that cookie's name news' business.
    """
    return await PagesService(db).publish(page_id)
