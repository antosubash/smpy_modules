"""Creating, translating and publishing the page an article's body lives in.

A sibling of :mod:`news.integrations.pagebuilder` rather than part of it: that
file is at the repo's 300-line cap, and these are the writes news performs *on*
a page, as against the reads and the routes it borrows. Same rule — nothing
outside ``news.integrations`` imports ``pagebuilder``.

Both writes run on the server so that creating an article is one request under
news' own CSRF token. The frontend used to POST to pagebuilder's page API
directly, which meant knowing pagebuilder's cookie name and priming it with a
throwaway GET — and left an orphaned, empty page behind whenever the second
call failed, because the two writes were in different transactions.
"""

from __future__ import annotations

from fastapi import HTTPException
from pagebuilder.contracts.schemas import PageCreate, PageTranslationCreate
from pagebuilder.models import Page
from pagebuilder.service import PagesService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from news.constants import MAX_SLUG_ATTEMPTS, MAX_SLUG_LEN
from news.integrations.locales import default_locale
from news.slugify import slugify

__all__ = [
    "create_article_page",
    "create_page_translation",
    "empty_puck_document",
    "publish_page",
    "slug_for_title",
]


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


async def _free_slug(db: AsyncSession, base: str, locale: str) -> str:
    """``base``, or ``base-2``, ``base-3``… — the first nobody is using.

    Scoped to one language, because slugs are: an English article called
    ``budget`` does not stop a German one taking the same address under
    ``/de/news/``, and suffixing it to ``budget-2`` would invent a URL for a
    collision that never happened.

    One query rather than one per candidate: the alternative is a
    create-and-catch-409 loop, and ``PagesService.create`` rolls the session
    back on conflict, which would discard anything the caller had already
    written in the same transaction.

    Returns ``""`` when even the suffixed candidates are all taken, which the
    caller turns into an error rather than guessing further.
    """
    # The prefilter is the *stem* rather than ``base``: a base already at
    # MAX_SLUG_LEN has to be cut to make room for the suffix, so its candidates
    # do not start with ``base`` and a ``startswith(base)`` filter would never
    # see them — handing back a candidate that is in fact taken.
    stem = base[: _stem_length(base)]
    taken = set(
        (
            await db.execute(
                select(Page.slug).where(
                    Page.locale == locale, Page.slug.startswith(stem)
                )
            )
        ).scalars()
    )
    if base not in taken:
        return base
    for suffix in range(2, MAX_SLUG_ATTEMPTS + 2):
        candidate = f"{base[: MAX_SLUG_LEN - len(str(suffix)) - 1]}-{suffix}"
        if candidate not in taken:
            return candidate
    return ""


def _stem_length(base: str) -> int:
    """How much of ``base`` every candidate is guaranteed to share.

    The longest suffix is the one that eats the most of the base, so cutting to
    that leaves a prefix common to ``base`` and to all of its variants.
    """
    longest = len(str(MAX_SLUG_ATTEMPTS + 1))
    return min(len(base), MAX_SLUG_LEN - longest - 1)


async def create_article_page(
    db: AsyncSession, *, title: str, slug: str | None = None, locale: str | None = None
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
    language = locale or default_locale()
    if slug:
        chosen = slug
    else:
        chosen = await _free_slug(db, slug_for_title(title), language)
        if not chosen:
            raise _slug_exhausted(title)
    return await PagesService(db).create(
        PageCreate(
            title=title,
            slug=chosen,
            locale=language,
            draft_data=empty_puck_document(title),
        )
    )


def _slug_exhausted(title: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=f"Could not derive a free URL from {title!r}. Set one explicitly.",
    )


async def create_page_translation(
    db: AsyncSession,
    page_id: int,
    *,
    locale: str,
    slug: str | None = None,
    title: str | None = None,
) -> Page:
    """The article's body, in another language.

    Delegated whole rather than reimplemented: a translated article is a
    translated page, and the sibling-group bookkeeping, the per-language slug
    search and the "already exists" conflict all belong to the module that owns
    the table. News' own part — a second ``NewsArticle`` row for the new page —
    is the caller's, in the same transaction.
    """
    return await PagesService(db).create_translation(
        page_id,
        PageTranslationCreate(locale=locale, slug=slug, title=title),
    )


async def publish_page(db: AsyncSession, page_id: int) -> Page:
    """Publish the page behind an article.

    Here rather than in the browser for the same reason as ``create``: the row
    menu's Publish used to POST to pagebuilder's API with a borrowed CSRF token,
    which is the last thing that made that cookie's name news' business.
    """
    return await PagesService(db).publish(page_id)
