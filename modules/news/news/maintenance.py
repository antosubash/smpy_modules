"""Repair passes that run outside a request.

Split from :mod:`news.service` because they answer a different question: the
listing module is about what a reader or an editor sees, while this is about
what the database is left holding when an event goes missing.
"""

from __future__ import annotations

from pagebuilder.models import Page
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from news.models import NewsArticle


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
