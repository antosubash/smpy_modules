"""Reads: the listings, the category facets, and the single-row lookups."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from news.constants import DEFAULT_LIMIT, MAX_LIMIT
from news.contracts.schemas import ArticleRead, CategoryCount
from news.integrations import pagebuilder as pb
from news.models import NewsArticle
from news.service._shared import base_query, to_read, visible


async def list_articles(
    db: AsyncSession,
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    category: str | None = None,
    uncategorised: bool = False,
    include_drafts: bool = False,
    undated_first: bool = False,
) -> tuple[list[ArticleRead], int]:
    """Newest first, undated last. Returns (items, total-before-paging).

    ``undated_first`` flips where the undated land: the admin list asks for
    them up front because an undated article is by definition work in
    progress — with pagination it would otherwise sit on the *last* page,
    burying exactly the row its author is about to set a date on.
    """
    stmt = base_query(include_drafts, category, uncategorised)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))

    # NULLS placement is explicit either way: SQLite and Postgres disagree
    # about where NULL lands on a DESC sort, so without this the two databases
    # disagree about where an undated article goes.
    order = NewsArticle.published_at.desc()
    order = order.nullsfirst() if undated_first else order.nullslast()
    stmt = (
        stmt.order_by(order, NewsArticle.id.desc()).limit(min(limit, MAX_LIMIT)).offset(offset)
    )

    rows = (await db.execute(stmt)).all()
    return [to_read(article, page) for article, page in rows], int(total or 0)


async def list_categories(
    db: AsyncSession, *, include_drafts: bool = False
) -> tuple[list[CategoryCount], int]:
    """Named categories with counts, plus how many articles carry none.

    Ordered by name. The uncategorised count comes back alongside the list
    rather than as a blank-named entry in it — see
    ``CategoryListResponse.uncategorised``.
    """
    stmt = (
        select(NewsArticle.category, func.count())
        .join(pb.Page, pb.Page.id == NewsArticle.page_id)
        .group_by(NewsArticle.category)
        .order_by(NewsArticle.category)
    )
    rows = (await db.execute(visible(stmt, include_drafts=include_drafts))).all()

    named = [CategoryCount(category=name, count=int(count)) for name, count in rows if name]
    uncategorised = sum(int(count) for name, count in rows if not name)
    return named, uncategorised


async def get_read_by_page(
    db: AsyncSession, page_id: int, *, include_drafts: bool = True
) -> ArticleRead | None:
    """One article in listing shape, found by page rather than by scanning.

    Shares ``base_query`` with the listing, so the response shape and the join
    semantics stay identical by construction rather than by convention. This
    exists because reading a just-written article back out of the first page of
    ``list_articles`` cannot work: a new article is undated and undated sorts
    last, so past a hundred dated articles it is simply not in that page.
    """
    stmt = base_query(include_drafts, None).where(NewsArticle.page_id == page_id)
    row = (await db.execute(stmt)).first()
    return to_read(row[0], row[1]) if row is not None else None


async def page_exists(db: AsyncSession, page_id: int) -> bool:
    """Whether the page an article would attach to is actually there.

    Checked explicitly because there is no foreign key to do it — and an
    article pointing at a missing page is not inert: SQLite reuses the id, so
    the row re-attaches to whatever page is created next.
    """
    return await db.scalar(select(pb.Page.id).where(pb.Page.id == page_id)) is not None


async def get_by_page(db: AsyncSession, page_id: int) -> NewsArticle | None:
    return await db.scalar(select(NewsArticle).where(NewsArticle.page_id == page_id))


async def get(db: AsyncSession, article_id: int) -> NewsArticle | None:
    return await db.scalar(select(NewsArticle).where(NewsArticle.id == article_id))
