"""Queries joining article metadata to the pages that hold the articles."""

from __future__ import annotations

from datetime import datetime

from pagebuilder.models import Page, PageStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from news.constants import DEFAULT_LIMIT, MAX_LIMIT
from news.contracts.schemas import ArticleRead, CategoryCount
from news.models import NewsArticle

PUBLIC_PAGE_URL = "/p/{slug}"


def _visible(stmt, *, include_drafts: bool):
    """Restrict to published pages unless the caller may see drafts."""
    if include_drafts:
        return stmt
    return stmt.where(Page.status == PageStatus.PUBLISHED)


def _base(include_drafts: bool, category: str | None):
    # INNER join, not outer: an article whose page was deleted has no row to
    # show, and this is what keeps such an orphan invisible rather than
    # rendering a card that links nowhere. There is no database foreign key —
    # see NewsArticle.page_id.
    stmt = select(NewsArticle, Page).join(Page, Page.id == NewsArticle.page_id)
    stmt = _visible(stmt, include_drafts=include_drafts)
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
        url=PUBLIC_PAGE_URL.format(slug=page.slug),
    )


async def list_articles(
    db: AsyncSession,
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    category: str | None = None,
    include_drafts: bool = False,
) -> tuple[list[ArticleRead], int]:
    """Newest first, undated last. Returns (items, total-before-paging)."""
    stmt = _base(include_drafts, category)

    total = await db.scalar(
        select(func.count()).select_from(stmt.subquery())
    )

    # NULLS LAST explicitly: SQLite sorts NULL first by default and Postgres
    # sorts it last on DESC, so without this the two databases disagree about
    # where an undated article lands.
    stmt = stmt.order_by(
        NewsArticle.published_at.desc().nullslast(), NewsArticle.id.desc()
    ).limit(min(limit, MAX_LIMIT)).offset(offset)

    rows = (await db.execute(stmt)).all()
    return [_to_read(article, page) for article, page in rows], int(total or 0)


async def list_categories(
    db: AsyncSession, *, include_drafts: bool = False
) -> list[CategoryCount]:
    """Distinct categories with counts, ordered by name. Blanks are omitted."""
    stmt = (
        select(NewsArticle.category, func.count())
        .join(Page, Page.id == NewsArticle.page_id)
        .where(NewsArticle.category != "")
        .group_by(NewsArticle.category)
        .order_by(NewsArticle.category)
    )
    stmt = _visible(stmt, include_drafts=include_drafts)
    rows = (await db.execute(stmt)).all()
    return [CategoryCount(category=name, count=int(count)) for name, count in rows]


async def get_by_page(db: AsyncSession, page_id: int) -> NewsArticle | None:
    return await db.scalar(select(NewsArticle).where(NewsArticle.page_id == page_id))


async def get(db: AsyncSession, article_id: int) -> NewsArticle | None:
    return await db.scalar(select(NewsArticle).where(NewsArticle.id == article_id))


async def create(
    db: AsyncSession, *, page_id: int, category: str, published_at: datetime | None
) -> NewsArticle:
    article = NewsArticle(page_id=page_id, category=category, published_at=published_at)
    db.add(article)
    await db.commit()
    await db.refresh(article)
    return article


async def update(
    db: AsyncSession,
    article: NewsArticle,
    *,
    category: str | None,
    published_at: datetime | None,
) -> NewsArticle:
    if category is not None:
        article.category = category
    # `published_at=None` is a real value (an undated article), so it is only
    # applied when the caller sent the field — the endpoint decides that.
    article.published_at = published_at
    db.add(article)
    await db.commit()
    await db.refresh(article)
    return article


async def delete(db: AsyncSession, article: NewsArticle) -> None:
    """Detach the article. The page itself is untouched."""
    await db.delete(article)
    await db.commit()
