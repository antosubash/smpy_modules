"""Per-status counts for the article list's filter pills.

Kept out of :mod:`news.service` so the listing module stays inside the 300-line
cap, and separate from a plain ``total`` because the two answer different
questions: ``total`` counts what the current filter selected, while these count
what each *other* filter would select. A pill showing the total would read the
same on every pill.
"""

from __future__ import annotations

from pagebuilder.models import Page, PageStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from news import query_filters
from news.contracts.schemas import ArticleCounts
from news.models import NewsArticle


async def count_by_status(
    db: AsyncSession,
    *,
    category: str | None = None,
    q: str | None = None,
    include_drafts: bool = False,
) -> ArticleCounts:
    """Counts within the current search and category scope.

    Deliberately *not* narrowed by the status filter — these are what each pill
    would show if you clicked it, so applying the active status would collapse
    every pill but one to zero.

    One grouped query rather than four counts: the list re-reads these on every
    keystroke of the search box.
    """
    stmt = (
        select(Page.status, NewsArticle.published_at.is_(None), func.count())
        .select_from(NewsArticle)
        .join(Page, Page.id == NewsArticle.page_id)
        .group_by(Page.status, NewsArticle.published_at.is_(None))
    )
    stmt = query_filters.visible(stmt, include_drafts=include_drafts)
    stmt = query_filters.search(stmt, q)
    if category:
        stmt = stmt.where(NewsArticle.category == category)

    counts = ArticleCounts()
    for status, undated, count in (await db.execute(stmt)).all():
        count = int(count)
        counts.all += count
        if status == PageStatus.PUBLISHED:
            counts.published += count
        elif status == PageStatus.DRAFT:
            counts.draft += count
        # Undated cuts across draft and published rather than being a third
        # status, so it is summed independently and the pills deliberately do
        # not add up to `all`.
        if undated:
            counts.undated += count
    return counts
