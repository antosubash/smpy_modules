"""Status transitions and the trash.

Mixed into :class:`~news.content.ArticlesService`. Every transition records a
revision, so the history is the audit log rather than something kept beside it.

An article's workflow used to be a pagebuilder page's. Owning the content means
owning the transitions, which is also what lets ``news.publish`` be a real gate
instead of a permission on somebody else's module.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from news.content._revisions import RevisionsMixin
from news.models import NOT_TRASHED, ArticleStatus, NewsArticle, RevisionEvent

_UNSET: Any = object()
"""Sentinel for "the caller did not mention this field".

``schedule`` has to tell an omitted argument from an explicit ``None``:
cancelling a schedule is a real instruction, and ``None`` is how it is spelt.
"""


class WorkflowMixin(RevisionsMixin):
    """Status behaviour for :class:`ArticlesService`.

    Inherits rather than sitting beside :class:`RevisionsMixin`, and that is
    load-bearing: every transition records a revision, so a sibling arrangement
    puts this class first in the MRO and its type-narrowing stub for
    ``_record_revision`` shadows the real implementation. Chaining them says
    what is actually true — workflow *needs* revisions.
    """

    db: AsyncSession

    async def _transition(
        self,
        article: NewsArticle,
        *,
        status: ArticleStatus,
        event: RevisionEvent,
        note: str | None = None,
    ) -> NewsArticle:
        """Apply a status change, record it, and return the refreshed row."""
        article.status = status
        # Cleared on every forward move so a stale rejection banner does not
        # shadow a new round. Only ``reject`` sets it, immediately after.
        article.rejection_note = note if event is RevisionEvent.REJECT else None
        self._record_revision(article, event=event, note=note)
        self.db.add(article)
        await self.db.flush()
        await self.db.refresh(article)
        return article

    async def publish(self, article_id: int) -> NewsArticle:
        """Snapshot the draft and serve it.

        ``published_data`` is a *copy* taken at this moment, not a reference to
        the draft: that is what lets an author keep editing a live article
        without every keystroke reaching its readers.
        """
        article = await self.get_article(article_id)
        article.published_data = article.draft_data
        # Acted on, so the intention is spent. Left set, the next tick would
        # find the article still due and publish it again every thirty seconds.
        article.publish_at = None
        return await self._transition(
            article, status=ArticleStatus.PUBLISHED, event=RevisionEvent.PUBLISH
        )

    async def schedule(
        self,
        article_id: int,
        *,
        publish_at: datetime | None = _UNSET,
        unpublish_at: datetime | None = _UNSET,
    ) -> NewsArticle:
        """Set or clear when an article goes live and comes down.

        Each argument is three-valued: omitted leaves the column alone, an
        instant sets it, and an explicit ``None`` clears it — cancelling a
        schedule has to be expressible, and is not the same as not mentioning
        it.

        No status change of its own. Scheduling is a statement about the future;
        the flip happens in :meth:`process_due` when the time arrives, so an
        article scheduled for next week is a draft all week.
        """
        article = await self.get_article(article_id)
        if publish_at is not _UNSET:
            article.publish_at = publish_at
        if unpublish_at is not _UNSET:
            article.unpublish_at = unpublish_at
        self.db.add(article)
        await self.db.flush()
        await self.db.refresh(article)
        return article

    async def process_due(self, now: datetime) -> list[NewsArticle]:
        """Flip every article whose scheduled moment has passed.

        Idempotent by construction: each tick re-queries, and both `publish` and
        `unpublish` clear the timestamp they acted on, so a process that was
        asleep for an hour catches up on its next wakeup rather than losing the
        window. One bad row is skipped rather than poisoning the whole tick.

        Trashed articles are excluded. An article binned while carrying a
        schedule must not republish itself out of the trash.
        """
        flipped: list[NewsArticle] = []

        due_to_publish = await self.db.execute(
            select(NewsArticle).where(
                NOT_TRASHED,
                NewsArticle.status == ArticleStatus.DRAFT,
                NewsArticle.publish_at.is_not(None),
                NewsArticle.publish_at <= now,
            )
        )
        for article in due_to_publish.scalars().all():
            try:
                flipped.append(await self.publish(article.id or 0))
            except HTTPException:
                continue

        due_to_unpublish = await self.db.execute(
            select(NewsArticle).where(
                NOT_TRASHED,
                NewsArticle.status == ArticleStatus.PUBLISHED,
                NewsArticle.unpublish_at.is_not(None),
                NewsArticle.unpublish_at <= now,
            )
        )
        for article in due_to_unpublish.scalars().all():
            try:
                flipped.append(await self.unpublish(article.id or 0))
            except HTTPException:
                continue

        return flipped

    async def unpublish(self, article_id: int) -> NewsArticle:
        """Take the article off the public site, keeping the draft.

        ``published_data`` is deliberately left behind. It is the last thing
        readers saw, and discarding it would make "what was live before I pulled
        it?" unanswerable — the revision history is for reading, not for
        rebuilding a served payload from.
        """
        article = await self.get_article(article_id)
        # Spent, like `publish_at` — otherwise the next tick takes it down again.
        article.unpublish_at = None
        return await self._transition(
            article, status=ArticleStatus.DRAFT, event=RevisionEvent.UNPUBLISH
        )

    async def submit_for_review(self, article_id: int) -> NewsArticle:
        article = await self.get_article(article_id)
        return await self._transition(
            article,
            status=ArticleStatus.SUBMITTED_FOR_REVIEW,
            event=RevisionEvent.SUBMIT,
        )

    async def approve(self, article_id: int) -> NewsArticle:
        """Approve *and* publish — one action, because approving a submission
        the reviewer then has to publish separately is a step that only ever
        gets forgotten."""
        article = await self.get_article(article_id)
        if article.status is not ArticleStatus.SUBMITTED_FOR_REVIEW:
            raise HTTPException(
                status_code=409, detail="Only a submitted article can be approved."
            )
        article.published_data = article.draft_data
        return await self._transition(
            article, status=ArticleStatus.PUBLISHED, event=RevisionEvent.APPROVE
        )

    async def reject(self, article_id: int, note: str | None = None) -> NewsArticle:
        article = await self.get_article(article_id)
        if article.status is not ArticleStatus.SUBMITTED_FOR_REVIEW:
            raise HTTPException(
                status_code=409, detail="Only a submitted article can be rejected."
            )
        return await self._transition(
            article,
            status=ArticleStatus.DRAFT,
            event=RevisionEvent.REJECT,
            note=note,
        )

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
        """
        article = await self.get_article(article_id, include_trashed=True)
        article.deleted_at = None
        self.db.add(article)
        await self.db.flush()
        await self.db.refresh(article)
        return article
