"""Optimistic concurrency for article edits, and the atomic status claim.

Both answer "has somebody else written to this row since I read it?", at two
different strengths. :func:`ensure_fresh` is the editor's courtesy check: a tab
that opened the article an hour ago is told so rather than silently overwriting
a newer save. :func:`claim_status` is the guarantee for workflow transitions: one
conditional ``UPDATE`` whose row count decides who won, so two requests racing
the same button cannot both succeed (see :mod:`news.content._claims` for the
same idea applied to the scheduler).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from news.models import ArticleStatus, NewsArticle
from news.naive_utc import as_utc

STALE_DETAIL = (
    "This article was changed somewhere else. Reload to get the latest version, "
    "then make your change again."
)


def ensure_fresh(article: NewsArticle, expected: datetime | None) -> None:
    """409 when *expected* is supplied and is not the stored ``updated_at``.

    Omitted means "do not check", which is what every caller written before
    this existed means. Both sides are normalised to UTC because SQLite hands
    back a naive instant.
    """
    if expected is not None and as_utc(expected) != as_utc(article.updated_at):
        raise HTTPException(status_code=409, detail=STALE_DETAIL)


async def claim_status(
    db: AsyncSession,
    article: NewsArticle,
    *,
    expected: Iterable[ArticleStatus],
    to: ArticleStatus,
    conflict: str,
) -> None:
    """Move the row to *to* only if it is still as this request read it.

    The predicate is the status the caller validated, so a duplicate of the same
    request — which finds the first one's write — updates nothing and gets a
    409, and records no revision. (Not ``updated_at``: SQLite stores a Core
    ``now()`` without fractional seconds, so equality on it is unreliable.) The caller
    must call this before touching the article's attributes, so that a loser
    leaves nothing dirty to flush.
    """
    result = await db.execute(
        update(NewsArticle)
        .where(NewsArticle.id == article.id, NewsArticle.status.in_(list(expected)))
        .values(status=to, updated_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail=conflict)
