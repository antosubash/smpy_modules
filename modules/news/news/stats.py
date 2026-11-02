"""The public article count behind the ``NewsStats`` block.

Kept out of :mod:`news.counts` on purpose. That module answers the admin list's
pills, per status, for an editor who may see drafts; this one answers an
*anonymous* page view with a single number, so it takes no ``include_drafts`` at
all. A flag a caller could flip is a flag a future caller would flip.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from news import query_filters
from news.models import NOT_TRASHED, NewsArticle


async def count_published(
    db: AsyncSession,
    *,
    category: str | None,
    locale: str | None,
    now: datetime,
) -> int:
    """How many articles a reader could open right now.

    The public listing's set, minus one rule the listing leaves to the
    scheduler: an article whose ``unpublish_at`` has passed stays ``published``
    until the next tick takes it down, and until then the listing and viewer
    still serve it. The count does not wait: a figure on a page should not
    include something whose embargo has already ended, and the difference is at
    most one scheduler interval.

    ``category`` and ``locale`` are optional; without them it counts every
    category and every language. ``now`` is a parameter so a test does not have
    to race the clock.
    """
    stmt = (
        select(func.count())
        .select_from(NewsArticle)
        .where(
            NOT_TRASHED,
            or_(NewsArticle.unpublish_at.is_(None), NewsArticle.unpublish_at > now),
        )
    )
    stmt = query_filters.visible(stmt, include_drafts=False)
    stmt = query_filters.locale(stmt, locale)
    if category:
        stmt = stmt.where(NewsArticle.category == category)
    return int((await db.execute(stmt)).scalar_one())


__all__ = ["count_published"]
