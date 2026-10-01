"""The trash: soft-delete and restore.

Split from :mod:`news.content._workflow` to keep it inside the 300-line cap.
Neither changes status, so neither records a revision.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from news.content._revisions import RevisionsMixin
from news.models import NewsArticle
from news.naive_utc import as_utc


def _elapsed(value: datetime | None, now: datetime) -> bool:
    """Whether a stored timestamp, once normalized to UTC, is due or past."""
    aware = as_utc(value)
    return aware is not None and aware <= now


class TrashMixin(RevisionsMixin):
    """Trash behaviour for :class:`ArticlesService`."""

    db: AsyncSession

    async def trash(self, article_id: int) -> NewsArticle:
        """Soft-delete. The slug stays claimed — see ``NewsArticle.deleted_at``."""
        article = await self.get_article(article_id)
        article.deleted_at = datetime.now(UTC)
        self.db.add(article)
        await self.db.flush()
        await self.db.refresh(article)
        return article

    async def restore(self, article_id: int) -> NewsArticle:
        """Bring an article back out of the trash, as it was.

        Its status is untouched: an article that was published when it was
        binned is published again, which is the only reading of "restore" that
        does not quietly change what readers can see.

        A schedule that elapsed while the article was trashed is a different
        matter: `process_due` was correctly skipping it while trashed, and
        must not treat coming back out of the trash as the moment that was
        waiting for. Only a *stale* (already-past) timestamp is cleared — one
        still in the future is exactly what the author asked for and stays.
        """
        article = await self.get_article(article_id, include_trashed=True)
        article.deleted_at = None
        now = datetime.now(UTC)
        if _elapsed(article.publish_at, now):
            article.publish_at = None
        if _elapsed(article.unpublish_at, now):
            article.unpublish_at = None
        self.db.add(article)
        await self.db.flush()
        await self.db.refresh(article)
        return article
