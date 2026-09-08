"""Reading articles — the listing, the archive and the single-row read-back.

Every query here used to be a join onto ``pagebuilder_pages``, because that is
where an article's title, slug and status lived. They are columns on
``NewsArticle`` now, so the listing is a single-table scan and an article can no
longer be orphaned by something happening in another module.

Writes ``flush`` rather than ``commit``: in a request the framework's ``get_db``
owns the transaction and commits on the way out, so committing here would take
that decision away from the endpoint and leave a row behind when the handler
goes on to raise.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Final

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from news import card, locales, query_filters, tag_service
from news.constants import DEFAULT_LIMIT, MAX_LIMIT
from news.contracts.schemas import ArticleRead, CategoryCount
from news.models import (
    NOT_TRASHED,
    NewsArticle,
    NewsArticleTag,
    NewsCategory,
    NewsTag,
)

logger = logging.getLogger(__name__)


class _Unset:
    """Sentinel type — a field the caller omitted, as distinct from a null."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNSET"


UNSET: Final = _Unset()
"""Passed for ``published_at`` when the caller did not send the field.

A typed singleton rather than a bare ``object()`` so ``datetime | None | _Unset``
stays a real union that a type checker can narrow with ``isinstance``.
"""


async def list_articles(
    db: AsyncSession,
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    category: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    authors: list[str] | None = None,
    status: str | None = None,
    locale: str | None = None,
    group: str | None = None,
    in_feed_only: bool = False,
    include_drafts: bool = False,
    undated_first: bool = False,
    trashed_only: bool = False,
    with_total: bool = True,
) -> tuple[list[ArticleRead], int]:
    """Newest first, undated last. Returns (items, total-before-paging).

    ``undated_first`` flips where the undated land: the admin list asks for
    them up front because an undated article is by definition work in
    progress — with pagination it would otherwise sit on the *last* page,
    burying exactly the row its author is about to set a date on.

    ``with_total=False`` skips the ``count(*)`` and reports ``0``, for the
    callers that have no pager to feed — the RSS feed takes a fixed window, so
    counting the archive behind it is a second full scan whose answer is thrown
    away. Default ``True``, because every paged caller needs the real number.
    """
    # A category arrives from the UI as a name and from a public link as a
    # slug. Resolving here rather than at each call site is what lets
    # /news?category=field-notes and the admin pill both filter the same rows.
    if category:
        category = await resolve_category_slug(db, category) or category

    stmt = card.base(include_drafts, category, trashed_only)
    if tag:
        # By slug or by name, for the same reason a category accepts both: the
        # public archive links carry the slug and the admin passes what the
        # writer typed. An unknown tag matches nothing rather than everything —
        # a mistyped tag URL should be an empty archive, not the whole one.
        stmt = stmt.where(
            NewsArticle.id.in_(
                select(NewsArticleTag.article_id).join(
                    NewsTag, NewsTag.id == NewsArticleTag.tag_id
                ).where(or_(NewsTag.slug == tag, NewsTag.name == tag))
            )
        )
    if in_feed_only:
        # Only the feed block asks for this. The admin list must keep showing
        # everything that exists, or an article hidden from the feed becomes
        # unreachable from the one screen that could un-hide it.
        stmt = stmt.where(NewsArticle.show_in_feed.is_(True))
    stmt = query_filters.search(stmt, q)
    # The bylines one author address means — usually one, occasionally two
    # spellings of the same person. Resolved by the caller (``news.authors``)
    # because the slug rule that maps between the two lives in Python, not in
    # SQL. ``[]`` narrows to nothing, which is what an unpublished byline means.
    stmt = query_filters.author(stmt, authors)
    # Public feeds pass the language the visitor is reading in, so a German
    # page's feed block lists German articles. The admin list leaves it unset
    # and shows every language, with a badge per row.
    stmt = query_filters.locale(stmt, locale)
    stmt = query_filters.translation_group(stmt, group)
    # A draft filter from someone who may not see drafts must not widen the
    # base query — `visible` has already restricted it, and `status` only
    # narrows, so the two compose safely in either order.
    stmt = query_filters.status(stmt, status)

    total = (
        await db.scalar(select(func.count()).select_from(stmt.subquery()))
        if with_total
        else 0
    )

    if include_drafts:
        # After the count, and only for a caller who may see drafts. Both
        # halves are load-bearing — see ``card.HAS_UNPUBLISHED_CHANGES``.
        stmt = stmt.add_columns(card.HAS_UNPUBLISHED_CHANGES)

    stmt = (
        query_filters.ordered(stmt, undated_first=undated_first)
        .limit(min(limit, MAX_LIMIT))
        .offset(offset)
    )

    rows = (await db.execute(stmt)).all()
    return [card.to_read(row) for row in rows], int(total or 0)


async def resolve_category_slug(db: AsyncSession, slug: str) -> str | None:
    """Category name for a slug, or ``None`` when no managed row matches.

    Kept here rather than imported from ``category_service`` so the listing
    path does not depend on the management module. Matches by slug or by
    name — like the tag filter above — so a caller that already resolved the
    slug (the archive routes do, for the page heading) still finds the row.
    """
    return await db.scalar(
        select(NewsCategory.name).where(or_(NewsCategory.slug == slug, NewsCategory.name == slug))
    )


async def list_categories(
    db: AsyncSession, *, include_drafts: bool = False
) -> list[CategoryCount]:
    """Counts per category, in the order the categories screen set. Blanks omitted.

    The order is the whole point: the categories screen exists to arrange the
    public filter bar, and that promise is only kept if this listing — the one
    the filter bar and the feed block actually call — reads the positions back.

    An outer join, because a category that has never been formalised on the
    management screen has no row to order by. Those keep sorting by name, after
    every ordered one, rather than vanishing from the filter bar.
    """
    stmt = (
        select(NewsArticle.category, func.count(), NewsCategory.position)
        .select_from(NewsArticle)
        .outerjoin(NewsCategory, NewsCategory.name == NewsArticle.category)
        .where(NOT_TRASHED, NewsArticle.category != "")
        .group_by(NewsArticle.category, NewsCategory.position)
        .order_by(NewsCategory.position.nullslast(), NewsArticle.category)
    )
    stmt = query_filters.visible(stmt, include_drafts=include_drafts)
    rows = (await db.execute(stmt)).all()
    return [CategoryCount(category=name, count=int(count)) for name, count, _ in rows]


async def get_read(
    db: AsyncSession, article_id: int, *, include_drafts: bool = True
) -> ArticleRead | None:
    """One article in listing shape.

    Shares ``card.base`` with the listing, so the response shape and the
    visibility rule stay identical by construction rather than by convention.
    This exists because reading a just-written article back out of the first
    page of ``list_articles`` cannot work: a new article is undated and undated
    sorts last, so past a hundred dated articles it is simply not in that page.
    """
    stmt = card.base(include_drafts, None).where(NewsArticle.id == article_id)
    if include_drafts:
        stmt = stmt.add_columns(card.HAS_UNPUBLISHED_CHANGES)
    row = (await db.execute(stmt)).first()
    return card.to_read(row) if row is not None else None


async def get(db: AsyncSession, article_id: int) -> NewsArticle | None:
    """The row itself, trashed ones excluded.

    ``ArticlesService.get_article`` is the write path's equivalent and raises;
    this returns ``None`` because its callers turn the miss into their own 404
    with their own wording.
    """
    return await db.scalar(
        select(NewsArticle).where(NOT_TRASHED, NewsArticle.id == article_id)
    )


async def get_by_slug(
    db: AsyncSession, slug: str, locale: str | None = None
) -> NewsArticle | None:
    """One article by address. Scoped to a language, because that is what an
    address is: a slug identifies an article only within one locale, so a
    lookup without it returns whichever translation the database reached
    first. ``None`` means the site's default language."""
    return await db.scalar(
        select(NewsArticle).where(
            NOT_TRASHED,
            NewsArticle.slug == slug,
            NewsArticle.locale == (locale or locales.default()),
        )
    )


async def update(
    db: AsyncSession,
    article: NewsArticle,
    *,
    category: str | None = None,
    published_at: datetime | _Unset | None = UNSET,
    pinned: bool | None = None,
    show_in_feed: bool | None = None,
    author: str | None = None,
) -> NewsArticle:
    """The listing metadata only — never the body, the slug or the status.

    Those go through :class:`news.content.ArticlesService`, which records a
    revision and a redirect where one is owed. Keeping them apart is what stops
    an inline edit in the admin list from quietly renaming a published URL.
    """
    if category is not None:
        article.category = category
    if pinned is not None:
        article.pinned = pinned
    if show_in_feed is not None:
        article.show_in_feed = show_in_feed
    if author is not None:
        article.author = author
    # `published_at=None` is a real value — it undates the article — so it is
    # applied only when the caller actually sent the field. The endpoint reads
    # `model_fields_set` to tell the two apart and passes UNSET otherwise.
    if not isinstance(published_at, _Unset):
        article.published_at = published_at
    db.add(article)
    await db.flush()
    await db.refresh(article)
    return article


async def delete(db: AsyncSession, article: NewsArticle) -> None:
    """Remove the article outright, tags and all.

    Tag links go explicitly, not by ``ondelete="CASCADE"`` — see
    :func:`news.tag_service.delete` for why that never fires here.
    """
    await tag_service.unlink_article(db, article.id or 0)
    await db.delete(article)
    await db.flush()
