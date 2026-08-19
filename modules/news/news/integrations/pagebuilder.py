"""The single place news knows what pagebuilder *is*.

An article is a pagebuilder page, so some coupling is the design rather than an
accident. What is avoidable is the coupling being *spread*: before this module
existed, ``pagebuilder`` was imported in the service, the contracts and the
module registration, and its CSRF cookie name and page API route were hardcoded
in the frontend. Six files had to be right for a framework bump to be safe.

Now the borrowing is declared once, in news' own vocabulary:

* the page table and status enum the listings join to,
* the ``PageDeleted`` event the orphan sweep hangs off,
* the service that creates the page an article's body will live in.

Nothing outside this package imports ``pagebuilder``. The rule is worth keeping
even where the re-export looks redundant, because it is what makes
``requires`` in ``pyproject.toml`` checkable by reading one file.
"""

from __future__ import annotations

import re
import unicodedata

from pagebuilder.contracts.events import PageDeleted
from pagebuilder.contracts.schemas import PageCreate
from pagebuilder.models import Page, PageStatus
from pagebuilder.service import PagesService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Load

from news.constants import MAX_SLUG_ATTEMPTS, MAX_SLUG_LEN
from news.contracts.schemas import ArticleStatus

__all__ = [
    "Page",
    "PageDeleted",
    "PageStatus",
    "article_status",
    "card_columns",
    "create_article_page",
    "empty_puck_document",
    "page_editor_path",
    "slugify",
]

PAGE_EDITOR_PATH = "/pagebuilder/{page_id}/edit"


def page_editor_path(page_id: int) -> str:
    """Where an author edits the body. Mirrors ``utils/pagebuilder.ts``."""
    return PAGE_EDITOR_PATH.format(page_id=page_id)


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
    return {"root": {"props": {"title": title, "width": "full"}}, "content": [], "zones": {}}

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Title -> slug, matching pagebuilder's ``PageCreate.slug`` pattern.

    That pattern is ``^[a-z0-9][a-z0-9-]*$``, so a leading hyphen — which a
    title starting with punctuation would otherwise produce — is a 422 rather
    than a cosmetic problem.
    """
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return _NON_SLUG.sub("-", folded.lower()).strip("-")[:MAX_SLUG_LEN].strip("-")


async def _free_slug(db: AsyncSession, base: str) -> str:
    """``base``, or ``base-2``, ``base-3``… — the first nobody is using.

    One query rather than one per candidate: the alternative is a create-and-
    catch-409 loop, and ``PagesService.create`` rolls the session back on
    conflict, which would discard anything the caller had already written.

    A concurrent create can still take the slug between this and the insert.
    That is what the caller's fallback suffix is for — losing a tidy slug to a
    race is a far better outcome than failing the request.
    """
    taken = set(
        (await db.execute(select(Page.slug).where(Page.slug.startswith(base)))).scalars()
    )
    if base not in taken:
        return base
    for suffix in range(2, MAX_SLUG_ATTEMPTS + 2):
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            return candidate
    return ""


async def create_article_page(db: AsyncSession, *, title: str, fallback_suffix: str) -> Page:
    """Create the page an article's body will live in, with a readable slug.

    This runs on the server so that creating an article is one request under
    news' own CSRF token. The frontend used to POST to pagebuilder's page API
    directly, which meant knowing pagebuilder's cookie name and priming it with
    a throwaway GET — and left an orphan page behind whenever the second call
    failed, because the two writes were in different transactions.

    ``fallback_suffix`` is only reached when a race takes the slug this just
    picked; it is unique by construction so the create cannot fail twice.
    """
    base = slugify(title) or fallback_suffix
    slug = await _free_slug(db, base) or f"{base}-{fallback_suffix}"
    return await PagesService(db).create(
        PageCreate(title=title, slug=slug, draft_data=empty_puck_document(title))
    )
