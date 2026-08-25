"""Revision recording, history and restore.

Mixed into :class:`~news.content.ArticlesService`. Split out to keep each file
inside the repo's 300-line cap; the methods rely on ``self.db`` and
``self.get_article`` from the composing class.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from news.models import NewsArticle, NewsArticleRevision, RevisionEvent


class RevisionsMixin:
    """Revision behaviour for :class:`ArticlesService`."""

    db: AsyncSession

    async def get_article(  # pragma: no cover - provided by ArticlesService
        self, article_id: int, *, include_trashed: bool = False
    ) -> NewsArticle:
        raise NotImplementedError

    def _record_revision(
        self,
        article: NewsArticle,
        *,
        event: RevisionEvent,
        note: str | None = None,
    ) -> NewsArticleRevision:
        """Append an audit row mirroring *article*'s current draft state.

        Publish / approve callers overwrite ``published_data`` with
        ``draft_data`` before recording, so ``draft_data`` is the single
        snapshot source every event needs. The caller owns the flush, so the
        article row and its revision land in one transaction.
        """
        revision = NewsArticleRevision(
            article_id=article.id or 0,
            title=article.title,
            meta_description=article.meta_description,
            og_image=article.og_image,
            data=article.draft_data,
            event=event,
            note=note,
        )
        self.db.add(revision)
        return revision

    async def list_revisions(self, article_id: int) -> list[NewsArticleRevision]:
        result = await self.db.execute(
            select(NewsArticleRevision)
            .where(NewsArticleRevision.article_id == article_id)
            .order_by(NewsArticleRevision.id.desc())
        )
        return list(result.scalars().all())

    async def get_revision(
        self, article_id: int, revision_id: int
    ) -> NewsArticleRevision:
        revision = await self.db.get(NewsArticleRevision, revision_id)
        if revision is None or revision.article_id != article_id:
            raise HTTPException(status_code=404, detail="Revision not found")
        return revision

    async def restore_revision(
        self, article_id: int, revision_id: int
    ) -> NewsArticle:
        """Copy a revision's payload into the article's draft.

        Deliberately does not publish. Restoring is an editing action — the
        author looks at what came back before deciding it should be live — and a
        restore that published would make an accidental click a public change.
        """
        article = await self.get_article(article_id)
        revision = await self.get_revision(article_id, revision_id)
        article.title = revision.title
        article.meta_description = revision.meta_description
        article.og_image = revision.og_image
        article.draft_data = revision.data
        self.db.add(article)
        await self.db.flush()
        await self.db.refresh(article)
        return article
