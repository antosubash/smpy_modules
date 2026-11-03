"""The public article count behind the ``NewsStats`` block.

Kept out of :mod:`news.counts` on purpose. That module answers the admin list's
pills, per status, for an editor who may see drafts; this one answers an
*anonymous* page view with a single number, so it takes no ``include_drafts`` at
all. A flag a caller could flip is a flag a future caller would flip.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from news.content import query_filters
from news.core import locales
from news.models import NOT_TRASHED, NewsArticle


def _counted_columns() -> list:
    """What the bounded count's inner query selects: every column but the bodies.

    The outer count runs over ``aliased(NewsArticle, <limited subquery>)`` so
    the statement still names the mapper, which is what the framework's tenant
    criteria attach to — and they are rendered against the *alias*, i.e. against
    the columns the subquery exposes. Exposing only ``id`` does not fail: the
    criterion falls back to the base table and the count becomes a cross join
    with every article (measured: 3 matches counted as 18). The JSON bodies
    are left out because no criterion names them and they are the bulk of a row.
    """
    return [
        getattr(NewsArticle, column.key)
        for column in NewsArticle.__table__.columns
        if not isinstance(column.type, JSON)
    ]


async def count_published(
    db: AsyncSession,
    *,
    category: str | None,
    locale: str | None,
    now: datetime,
    cap: int,
) -> tuple[int, bool]:
    """``(count, capped)``: how many articles a reader could open right now.

    The public listing's set, minus one rule the listing leaves to the
    scheduler: an article whose ``unpublish_at`` has passed stays ``published``
    until the next tick takes it down, and until then the listing and viewer
    still serve it. The count does not wait: a figure on a page should not
    include something whose embargo has already ended, and the difference is at
    most one scheduler interval.

    **Only the site's languages.** An article keeps its ``locale`` when that
    language is taken off the site, but its public route is gone with it, so
    "every language" means every *configured* one, and a named locale goes
    through :func:`news.core.locales.resolve` as the public routes' does: a removed
    or unknown one counts nothing rather than everything.

    **Bounded.** The route is anonymous and a cache miss is anyone's to cause,
    so the count reads at most ``cap + 1`` rows and answers ``(cap, True)``
    past it — the shape records' stats use. See :func:`_counted_columns` for
    how the tenant filter survives the subquery.

    ``category`` and ``locale`` are optional; without them it counts every
    category and every configured language. ``now`` is a parameter so a test
    does not have to race the clock.
    """
    if locale:
        resolved = locales.resolve(locale)
        if resolved is None:
            return 0, False
        languages: tuple[str, ...] = (resolved,)
    else:
        languages = locales.supported()
    inner = select(*_counted_columns()).where(
        NOT_TRASHED,
        NewsArticle.locale.in_(languages),
        or_(NewsArticle.unpublish_at.is_(None), NewsArticle.unpublish_at > now),
    )
    inner = query_filters.visible(inner, include_drafts=False)
    if category:
        inner = inner.where(NewsArticle.category == category)
    counted = aliased(NewsArticle, inner.limit(cap + 1).subquery())
    stmt = select(func.count(counted.id)).select_from(counted)
    total = int((await db.execute(stmt)).scalar_one())
    return (cap, True) if total > cap else (total, False)


__all__ = ["count_published"]
