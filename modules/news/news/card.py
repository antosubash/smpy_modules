"""What a listing selects, and the shape it hands back.

Two halves of one decision, kept in one file. The columns a card reads used to
live in :mod:`news.service` and the unpacking of them here, joined by a comment
in each pointing at the other — so adding a field meant editing both files and
remembering which order they had to agree in. They are the same decision: this
is the one place the wire shape of an article is chosen, and the listing, the
single-article read and the editor's detail shape — which widens this one —
all come through it.

It takes a *row*, not an entity. Selecting the whole ``NewsArticle`` drags both
block-JSON columns through the ORM for every row, so list cost would scale with
article *content* size instead of card count — the regression that made this a
rule for the sidecar's join (issue #12) and is now this module's own to keep.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import Text, and_, cast, func, select

from news import query_filters
from news.constants import ARTICLE_BODY_URL
from news.contracts.schemas import ArticleRead
from news.models import NOT_TRASHED, ArticleStatus, NewsArticle
from news.settings import public_article_path

COLUMNS: Final = (
    NewsArticle.id,
    NewsArticle.slug,
    NewsArticle.title,
    NewsArticle.meta_description,
    NewsArticle.og_image,
    NewsArticle.status,
    NewsArticle.category,
    NewsArticle.pinned,
    NewsArticle.show_in_feed,
    NewsArticle.author,
    NewsArticle.published_at,
    # The card's public URL is locale-prefixed and the editor's language
    # switcher keys off the group, so both are read on every row.
    NewsArticle.locale,
    NewsArticle.translation_group,
)
"""The only columns a card reads. Named explicitly — see the module docstring."""

_JSON_NULL: Final = "null"
"""What a JSON column holds for a Python ``None``.

Not SQL ``NULL``: SQLAlchemy's ``JSON`` persists ``None`` as the JSON text
``null``, so ``published_data IS NOT NULL`` is true of an article that has
never been published. :func:`news.redirects.resolve` hit the same thing and
answers it in Python, where it loads one row; a listing cannot afford that.
"""

_SNAPSHOT_TEXT: Final = func.coalesce(cast(NewsArticle.published_data, Text), _JSON_NULL)
"""The served snapshot as text — ``'null'`` for an article that has none.

Cast because the comparison has to run in the database. A ``json`` column has
no equality operator on Postgres, and the point of comparing there at all is
that only the answer crosses the wire: pulling both documents into Python per
row is exactly what ``COLUMNS`` exists to prevent.
"""

HAS_UNPUBLISHED_CHANGES: Final = and_(
    NewsArticle.status == ArticleStatus.PUBLISHED,
    # A binned article keeps its status and its snapshot, and the viewer 404s
    # it anyway. Every listing but the trash has already filtered these out;
    # the trash has not, and a row there claiming readers are being served
    # something would be describing readers who get a 404.
    NOT_TRASHED,
    _SNAPSHOT_TEXT != _JSON_NULL,
    cast(NewsArticle.draft_data, Text) != _SNAPSHOT_TEXT,
).label("has_unpublished_changes")
"""Readers are being served an older document than the one you are looking at.

The SQL half of ``endpoints.views._preview_state``'s rule, and deliberately the
same rule: an article is flagged only when it is *genuinely live* — published
**and** holding a snapshot — and its draft has since diverged. A draft holding
an old snapshot from before it was taken down is not that case; there is
nothing live for it to diverge from, and saying otherwise would be a sentence
about readers who are being served nothing. ``test_pending_edits`` pins the two
to each other.

Selected only for a caller who may see drafts, and only after the ``count(*)``
has been taken: it is a statement about editorial work in progress, so an
anonymous card must not carry it, and evaluated inside the counted subquery it
would compare both documents of every article in the archive to answer a
question about a page of twelve.

Compared as serialised text, which is what makes it cheap. Two documents that
are equal in Python but were serialised with their keys in a different order
read as diverged here — over-reporting, which is the safe direction: a badge
saying "there are edits" when there are none is a smaller lie than a live
article quietly hiding that readers see something else.
"""


def base(include_drafts: bool, category: str | None, trashed_only: bool = False):
    """The ``SELECT`` every card listing starts from.

    The trash is the one listing that asks for the complement of the filter
    every other listing applies. Spelt here rather than by a caller dropping
    the ``where``, so there is still exactly one place that decides what
    "trashed" means.
    """
    stmt = select(*COLUMNS).where(
        NewsArticle.deleted_at.is_not(None) if trashed_only else NOT_TRASHED
    )
    stmt = query_filters.visible(stmt, include_drafts=include_drafts)
    if category:
        stmt = stmt.where(NewsArticle.category == category)
    return stmt


def to_read(row) -> ArticleRead:
    """One card row — the ``COLUMNS`` tuple — as the published DTO."""
    return ArticleRead(
        id=row.id or 0,
        slug=row.slug,
        title=row.title,
        excerpt=row.meta_description or "",
        cover_image_url=row.og_image or "",
        category=row.category,
        tags=[],
        pinned=row.pinned,
        show_in_feed=row.show_in_feed,
        author=row.author,
        published_at=row.published_at,
        status=row.status,
        locale=row.locale,
        translation_group=row.translation_group,
        # Absent unless the caller may see drafts — see
        # ``HAS_UNPUBLISHED_CHANGES``. Absent reads as False rather than as an
        # error, because a card that is allowed to omit it is a card that must
        # not claim it.
        has_unpublished_changes=bool(getattr(row, "has_unpublished_changes", False)),
        # Locale-prefixed, so a German article's card links to the German
        # address rather than to a URL where only the English one answers.
        url=public_article_path(row.slug, row.locale),
        # Served rather than assembled in the browser, so the admin list holds
        # no opinion about how this module routes its own body canvas.
        edit_url=ARTICLE_BODY_URL.format(article_id=row.id or 0),
    )
