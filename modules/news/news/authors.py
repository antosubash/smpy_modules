"""Turning a byline into an address.

A category and a tag are managed rows with slugs of their own. ``author`` is
not, deliberately: a byline outlives the account, so it is free text on the
article rather than a reference to a user row somebody can delete. That leaves
the author archive with no slug column to read.

So the address is *derived* — with the same rule that slugs a category, via
:func:`news.slugify.slugify`, because a third spelling of that rule is a third
thing that can drift — and resolved by slugging the stored bylines back and
comparing. There is no ``author_service`` beside ``category_service`` and
``tag_service`` because there is nothing to manage: no table, no second
authoring surface, no migration, and no screen on which somebody would have to
keep a list of authors in step with the bylines actually typed.

Two consequences, both deliberate.

**Two spellings share one page.** "A. Subash" and "A Subash" both slug to
``a-subash``, and that page lists the articles filed under either. This is the
right way to fail: a byline entered two ways is overwhelmingly one person
entered inconsistently, and an address that served one spelling while hiding
the other would lose a reader exactly the articles they came for. Where they
genuinely are two people the remedy is editorial and free — distinguish the
bylines — rather than a schema change nobody can undo.

**A byline with no ASCII to fold onto has no page.** ``slug_for`` returns ``""``
for one, the viewer renders it as plain text rather than as a link, and it is
absent from the sitemap. Handing every such byline the slugifier's *fallback*
would be the one real data loss available here: unrelated authors collapsed
onto a single archive that claims to be each of them.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from news.constants import MAX_SLUG_LEN
from news.models import NOT_TRASHED, ArticleStatus, NewsArticle
from news.slugify import slugify

_LISTED = (
    NOT_TRASHED,
    NewsArticle.status == ArticleStatus.PUBLISHED,
    # The archive's own filter. An author page is an archive page, so a byline
    # whose only article is held out of listings has nothing to fill one.
    NewsArticle.show_in_feed.is_(True),
    NewsArticle.author != "",
)
"""What has to be true of an article for its byline to have an archive."""


def slug_for(author: str) -> str:
    """A byline's URL segment, or ``""`` when it has no address.

    ``fallback=""`` rather than the slugifier's default is the whole point:
    every byline that transliterates to nothing would otherwise share one slug,
    and one archive page would claim to be several unrelated people. An empty
    answer means "this byline is not addressable", which callers render as
    plain text.
    """
    return slugify(author, fallback="", max_length=MAX_SLUG_LEN)


async def bylines(db: AsyncSession, locale: str) -> list[tuple[str, int]]:
    """Every byline with something to show in one language, most-used first.

    One grouped scan rather than a slug comparison in SQL, because the slug
    does not exist in SQL: it is derived in Python from a rule that folds
    accents, and reproducing that in a ``WHERE`` clause would be the fourth
    copy of the one rule this module is careful to keep single. The set is
    bounded by the number of distinct bylines a publication has — tens, not
    rows — and the pages that call it are cached like the rest of the archive.

    Ordered by count and then by name so the answer is deterministic: the
    display spelling below is picked off the front of this list.
    """
    rows = await db.execute(
        select(NewsArticle.author, func.count())
        .where(*_LISTED, NewsArticle.locale == locale)
        .group_by(NewsArticle.author)
        .order_by(func.count().desc(), NewsArticle.author)
    )
    return [(name, int(count)) for name, count in rows.all()]


async def resolve(
    db: AsyncSession, slug: str, locale: str
) -> tuple[list[str], str | None]:
    """Which bylines this address means, and what to call the page.

    Returns every spelling slugging to ``slug`` — usually one — and the one to
    show as the heading, which is the spelling used on the most articles with
    ties broken alphabetically. Titling the page with the majority spelling is
    what makes a page collecting "A. Subash" and "A Subash" read as the byline
    the publication mostly uses rather than as whichever row came back first.

    ``([], None)`` for a byline nobody has published under in this language.
    The caller renders that as an empty archive, not a 404 — a byline can be
    edited off the last article carrying it, and a URL published while it
    existed should say "nothing here now" rather than "never existed", which is
    the rule an unknown tag already follows.
    """
    if not slug:
        return [], None
    matches = [name for name, _ in await bylines(db, locale) if slug_for(name) == slug]
    return matches, matches[0] if matches else None
