"""Revision recording, history and restore.

Mixed into :class:`~news.content.ArticlesService`. The root of the mixin chain:
what the chain needs from the composing class is declared by
:class:`~news.content._host.ArticlesHost`.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from news.content._host import HostBase
from news.models import NewsArticle, NewsArticleRevision, RevisionEvent


async def clear_revisions(db: AsyncSession, article_id: int) -> None:
    """Drop an article's history when the article itself is deleted.

    ``ondelete="CASCADE"`` only fires where the database enforces foreign keys,
    and SQLite does not unless ``PRAGMA foreign_keys=ON`` is set. Left behind,
    the rows are keyed on an id SQLite will happily hand to the next article
    inserted after the highest one is deleted — whose history panel would then
    open on somebody else's revisions.
    """
    await db.execute(
        sa_delete(NewsArticleRevision).where(NewsArticleRevision.article_id == article_id)
    )


class RevisionsMixin(HostBase):
    """Revision behaviour for :class:`ArticlesService`."""

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

    async def get_revision(self, article_id: int, revision_id: int) -> NewsArticleRevision:
        revision = await self.db.get(NewsArticleRevision, revision_id)
        if revision is None or revision.article_id != article_id:
            raise HTTPException(status_code=404, detail="Revision not found")
        return revision

    async def restore_revision(self, article_id: int, revision_id: int) -> NewsArticle:
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
