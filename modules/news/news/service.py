"""Queries joining article metadata to the pages that hold the articles.

Writes ``flush`` rather than ``commit``: in a request the framework's ``get_db``
owns the transaction and commits on the way out, so committing here would take
that decision away from the endpoint and leave a row behind when the handler
goes on to raise. The two callers outside a request — the ``PageDeleted``
subscription and the startup sweep, both in :mod:`news.module` — open their own
session and commit it themselves.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Final

from pagebuilder.models import Page, PageStatus
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Load

from news.constants import DEFAULT_LIMIT, MAX_LIMIT
from news.contracts.schemas import ArticleRead, CategoryCount
from news import query_filters
from news.models import NewsArticle, NewsCategory

logger = logging.getLogger(__name__)

PUBLIC_PAGE_URL = "/p/{slug}"


class _Unset:
    """Sentinel type — a field the caller omitted, as distinct from a null."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNSET"


UNSET: Final = _Unset()
"""Passed for ``published_at`` when the caller did not send the field.

A typed singleton rather than a bare ``object()`` so ``datetime | None | _Unset``
stays a real union that a type checker can narrow with ``isinstance``.
"""


def _base(include_drafts: bool, category: str | None):
    # INNER join, not outer: an article whose page was deleted has no row to
    # show, and this is what keeps such an orphan invisible rather than
    # rendering a card that links nowhere. There is no database foreign key —
    # see NewsArticle.page_id.
    #
    # load_only: the card serializer reads five Page columns; without it the
    # join dragged both block-JSON columns through the ORM for every row, so
    # list cost scaled with page *content* size instead of card count
    # (issue #12). Anything outside this list raises on access — loudly, in
    # tests — rather than silently re-widening the query.
    #
    # ``status`` is in the set because ``_to_read`` serializes ``page_status``;
    # leaving it out lazy-loads on access, which raises MissingGreenlet under
    # the async session (issue #20).
    stmt = (
        select(NewsArticle, Page)
        .join(Page, Page.id == NewsArticle.page_id)
        .options(
            Load(Page).load_only(
                Page.slug,
                Page.title,
                Page.meta_description,
                Page.og_image,
                Page.status,
            )
        )
    )
    stmt = query_filters.visible(stmt, include_drafts=include_drafts)
    if category:
        stmt = stmt.where(NewsArticle.category == category)
    return stmt


def _to_read(article: NewsArticle, page: Page) -> ArticleRead:
    return ArticleRead(
        id=article.id or 0,
        page_id=article.page_id,
        slug=page.slug,
        title=page.title,
        excerpt=page.meta_description or "",
        cover_image_url=page.og_image or "",
        category=article.category,
        published_at=article.published_at,
        page_status=page.status,
        url=PUBLIC_PAGE_URL.format(slug=page.slug),
    )


async def list_articles(
    db: AsyncSession,
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    category: str | None = None,
    q: str | None = None,
    status: str | None = None,
    include_drafts: bool = False,
    undated_first: bool = False,
) -> tuple[list[ArticleRead], int]:
    """Newest first, undated last. Returns (items, total-before-paging).

    ``undated_first`` flips where the undated land: the admin list asks for
    them up front because an undated article is by definition work in
    progress — with pagination it would otherwise sit on the *last* page,
    burying exactly the row its author is about to set a date on.
    """
    # A category arrives from the UI as a name and from a public link as a
    # slug. Resolving here rather than at each call site is what lets
    # /news?category=field-notes and the admin pill both filter the same rows.
    if category:
        category = await resolve_category_slug(db, category) or category

    stmt = _base(include_drafts, category)
    stmt = query_filters.search(stmt, q)
    # A draft filter from someone who may not see drafts must not widen the
    # base query — `visible` has already restricted it, and `status` only
    # narrows, so the two compose safely in either order.
    stmt = query_filters.status(stmt, status)

    total = await db.scalar(
        select(func.count()).select_from(stmt.subquery())
    )

    # NULLS placement is explicit either way: SQLite and Postgres disagree
    # about where NULL lands on a DESC sort, so without this the two databases
    # disagree about where an undated article goes.
    order = NewsArticle.published_at.desc()
    order = order.nullsfirst() if undated_first else order.nullslast()
    stmt = stmt.order_by(order, NewsArticle.id.desc()).limit(
        min(limit, MAX_LIMIT)
    ).offset(offset)

    rows = (await db.execute(stmt)).all()
    return [_to_read(article, page) for article, page in rows], int(total or 0)


async def resolve_category_slug(db: AsyncSession, slug: str) -> str | None:
    """Category name for a slug, or ``None`` when no managed row matches.

    Kept here rather than imported from ``category_service`` so the listing
    path does not depend on the management module.
    """
    return await db.scalar(select(NewsCategory.name).where(NewsCategory.slug == slug))


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
        .join(Page, Page.id == NewsArticle.page_id)
        .outerjoin(NewsCategory, NewsCategory.name == NewsArticle.category)
        .where(NewsArticle.category != "")
        .group_by(NewsArticle.category, NewsCategory.position)
        .order_by(NewsCategory.position.nullslast(), NewsArticle.category)
    )
    stmt = query_filters.visible(stmt, include_drafts=include_drafts)
    rows = (await db.execute(stmt)).all()
    return [CategoryCount(category=name, count=int(count)) for name, count, _ in rows]


async def get_read_by_page(
    db: AsyncSession, page_id: int, *, include_drafts: bool = True
) -> ArticleRead | None:
    """One article in listing shape, found by page rather than by scanning.

    Shares ``_base`` with the listing, so the response shape and the join
    semantics stay identical by construction rather than by convention. This
    exists because reading a just-written article back out of the first page of
    ``list_articles`` cannot work: a new article is undated and undated sorts
    last, so past a hundred dated articles it is simply not in that page.
    """
    stmt = _base(include_drafts, None).where(NewsArticle.page_id == page_id)
    row = (await db.execute(stmt)).first()
    return _to_read(row[0], row[1]) if row is not None else None


async def reconcile_orphans(db: AsyncSession) -> int:
    """Delete article rows whose page is gone. Returns how many.

    The ``PageDeleted`` subscription is the fast path, but it is best-effort:
    ``EventBus.publish`` gathers handlers with ``return_exceptions=True`` and
    logs a failure instead of raising, and pagebuilder commits the page deletion
    *before* publishing. A dropped event therefore leaves the row behind
    permanently, with nothing to retry it.

    That is not merely untidy. Every listing inner-joins the page, so the orphan
    is invisible — until SQLite reuses the deleted page's id, at which point the
    row re-attaches to whatever page is created next and the feed renders one
    article's category and date against another article's page.

    The caller owns the transaction; this does not commit.
    """
    orphaned = select(NewsArticle.id).where(
        ~select(Page.id).where(Page.id == NewsArticle.page_id).exists()
    )
    result = await db.execute(
        sa_delete(NewsArticle).where(NewsArticle.id.in_(orphaned))
    )
    return result.rowcount or 0


async def page_exists(db: AsyncSession, page_id: int) -> bool:
    """Whether the page an article would attach to is actually there.

    Checked explicitly because there is no foreign key to do it — and an
    article pointing at a missing page is not inert: SQLite reuses the id, so
    the row re-attaches to whatever page is created next.
    """
    return await db.scalar(select(Page.id).where(Page.id == page_id)) is not None


async def get_by_page(db: AsyncSession, page_id: int) -> NewsArticle | None:
    return await db.scalar(select(NewsArticle).where(NewsArticle.page_id == page_id))


async def get(db: AsyncSession, article_id: int) -> NewsArticle | None:
    return await db.scalar(select(NewsArticle).where(NewsArticle.id == article_id))


async def create(
    db: AsyncSession, *, page_id: int, category: str, published_at: datetime | None
) -> NewsArticle:
    article = NewsArticle(page_id=page_id, category=category, published_at=published_at)
    db.add(article)
    await db.flush()
    await db.refresh(article)
    return article


async def update(
    db: AsyncSession,
    article: NewsArticle,
    *,
    category: str | None = None,
    published_at: datetime | _Unset | None = UNSET,
) -> NewsArticle:
    if category is not None:
        article.category = category
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
    """Detach the article. The page itself is untouched."""
    await db.delete(article)
    await db.flush()
