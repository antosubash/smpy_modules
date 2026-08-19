"""Writes, plus the orphan sweep.

These ``flush`` rather than ``commit``: in a request the framework's ``get_db``
owns the transaction and commits on the way out, so committing here would take
that decision away from the endpoint and leave a row behind when the handler
goes on to raise. The two callers outside a request — the ``PageDeleted``
subscription and the startup sweep, both in :mod:`news.module` — open their own
session and commit it themselves.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from news.integrations import pagebuilder as pb
from news.models import NewsArticle
from news.service._shared import UNSET, _Unset, as_display_date


async def create(
    db: AsyncSession, *, page_id: int, category: str, published_at: datetime | None
) -> NewsArticle:
    article = NewsArticle(
        page_id=page_id, category=category, published_at=as_display_date(published_at)
    )
    db.add(article)
    await db.flush()
    await db.refresh(article)
    return article


def _unique_suffix() -> str:
    """A slug suffix nothing can already be using.

    Only reached when a concurrent create takes the readable slug between it
    being chosen and being inserted; the point is that the author's request
    still succeeds rather than failing on a race they cannot see or retry
    meaningfully.
    """
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")


async def create_page_and_article(
    db: AsyncSession, *, title: str, category: str, published_at: datetime | None
) -> NewsArticle:
    """The whole "New article" flow, in one transaction.

    Both writes live in the caller's transaction, so a failure attaching the
    article rolls the page back with it. The browser-side version could not do
    that — its two requests committed separately, so any failure of the second
    stranded an empty, articleless page in pagebuilder that nothing would ever
    clean up, and every retry stranded another.
    """
    page = await pb.create_article_page(db, title=title, fallback_suffix=_unique_suffix())
    return await create(db, page_id=page.id or 0, category=category, published_at=published_at)


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
        article.published_at = as_display_date(published_at)
    db.add(article)
    await db.flush()
    await db.refresh(article)
    return article


async def delete(db: AsyncSession, article: NewsArticle) -> None:
    """Detach the article. The page itself is untouched."""
    await db.delete(article)
    await db.flush()


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
        ~select(pb.Page.id).where(pb.Page.id == NewsArticle.page_id).exists()
    )
    result = await db.execute(sa_delete(NewsArticle).where(NewsArticle.id.in_(orphaned)))
    return result.rowcount or 0
