"""Status transitions and the trash.

Mixed into :class:`~news.content.ArticlesService`. Every transition records a
revision, so the history is the audit log rather than something kept beside it.

An article's workflow used to be a pagebuilder page's. Owning the content means
owning the transitions, which is also what lets ``news.publish`` be a real gate
instead of a permission on somebody else's module.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from news.content._claims import claim, due_candidates, release, retire_missed_windows
from news.content._fresh import claim_status
from news.content._trash import TrashMixin, _elapsed
from news.models import ArticleStatus, NewsArticle, RevisionEvent
from news.naive_utc import as_utc

logger = logging.getLogger(__name__)

_UNSET: Any = object()
"""Sentinel for "the caller did not mention this field".

``schedule`` has to tell an omitted argument from an explicit ``None``:
cancelling a schedule is a real instruction, and ``None`` is how it is spelt.
"""


class WorkflowMixin(TrashMixin):
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
        if (
            article.status is ArticleStatus.PUBLISHED
            and article.published_data == article.draft_data
            and article.publish_at is None
        ):
            # Already live and identical: publishing again would only add a
            # history row saying nothing happened.
            return article
        await claim_status(
            self.db,
            article,
            expected=(article.status,),
            to=ArticleStatus.PUBLISHED,
            conflict="This article was just changed by someone else. Reload and try again.",
        )
        article.published_data = article.draft_data
        # Spent: left set, the next tick would publish it again.
        article.publish_at = None
        # A genuinely future `unpublish_at` is a real "take it down later"
        # instruction and survives — process_due still needs it. One that has
        # already elapsed is a leftover from a schedule this publish did not
        # go through, and would take the article straight back down on the
        # next tick.
        if _elapsed(article.unpublish_at, datetime.now(UTC)):
            article.unpublish_at = None
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

        Rejects ``publish_at >= unpublish_at`` with a 422: that ordering would
        have :meth:`process_due` take the article back down in the same tick
        (or before) it went live.
        """
        article = await self.get_article(article_id)
        new_publish = as_utc(article.publish_at if publish_at is _UNSET else publish_at)
        new_unpublish = as_utc(article.unpublish_at if unpublish_at is _UNSET else unpublish_at)
        if new_publish is not None and new_unpublish is not None and new_publish >= new_unpublish:
            raise HTTPException(
                status_code=422, detail="publish_at must be strictly before unpublish_at"
            )
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

        Safe to run in more than one process. Each row is *claimed* before it is
        touched — one conditional ``UPDATE`` that clears the timestamp it is
        acting on, whose affected-row count says whether this caller won it — so
        two replicas ticking at the same instant flip a due article exactly
        once. :mod:`news.content._claims` has the shape and the reasoning; the
        two steps are spelt out here rather than hidden behind one call because
        the gap between them is the whole subject.

        Idempotent by construction: each tick re-queries, and both `publish` and `unpublish` clear
        the timestamp they acted on, so a process asleep an hour catches up rather than losing the
        window — unless the whole window passed while it slept, which is retired unpublished (see
        `retire_missed_windows`). One bad row is skipped rather than poisoning the whole tick —
        its claim handed straight back, so a later tick retries instead of the
        schedule dying here — but never silently: each skip is logged with the
        article's id, because a schedule that quietly never fires leaves no
        other trace anywhere.

        Trashed articles are excluded. An article binned while carrying a
        schedule must not republish itself out of the trash.
        """
        if missed := await retire_missed_windows(self.db, now):
            logger.warning("news.scheduler.window_missed count=%s", missed)
        flipped: list[NewsArticle] = []
        for label, column, status, act in (
            ("publish", NewsArticle.publish_at, ArticleStatus.DRAFT, self.publish),
            ("unpublish", NewsArticle.unpublish_at, ArticleStatus.PUBLISHED, self.unpublish),
        ):
            for article_id, due_at in await due_candidates(
                self.db, column=column, status=status, now=now
            ):
                if not await claim(
                    self.db, article_id, column=column, status=status, now=now
                ):
                    # Another replica got there first, or a person did. Not a
                    # failure and not worth a line in the log: the article is
                    # being flipped, just not by us.
                    continue
                try:
                    flipped.append(await act(article_id))
                except HTTPException as exc:
                    # Warned rather than swallowed: a schedule that never fires
                    # is invisible otherwise, and "the article did not go live"
                    # is the kind of thing nobody notices until a reader asks
                    # about it.
                    await release(self.db, article_id, column=column, when=due_at)
                    logger.warning(
                        "news.scheduler.%s_failed article_id=%s: %s",
                        label,
                        article_id,
                        exc.detail,
                        extra={"article_id": article_id, "status_code": exc.status_code},
                    )
        return flipped

    async def unpublish(self, article_id: int) -> NewsArticle:
        """Take the article off the public site, keeping the draft.

        ``published_data`` is deliberately left behind. It is the last thing
        readers saw, and discarding it would make "what was live before I pulled
        it?" unanswerable — the revision history is for reading, not for
        rebuilding a served payload from.
        """
        article = await self.get_article(article_id)
        await claim_status(
            self.db,
            article,
            expected=(ArticleStatus.PUBLISHED,),
            to=ArticleStatus.DRAFT,
            conflict="Only a published article can be unpublished.",
        )
        # Both timestamps are spent here, for two different reasons.
        # `unpublish_at` because the next tick would otherwise take it down
        # again; `publish_at` because a retraction a stale schedule can undo is
        # not a retraction — this leaves the article a DRAFT, which is exactly
        # the shape `process_due` looks for, so a date left over from before it
        # went live would quietly serve it again.
        article.unpublish_at = None
        article.publish_at = None
        return await self._transition(
            article, status=ArticleStatus.DRAFT, event=RevisionEvent.UNPUBLISH
        )

    async def submit_for_review(self, article_id: int) -> NewsArticle:
        article = await self.get_article(article_id)
        if article.status is not ArticleStatus.DRAFT:
            raise HTTPException(409, "Only a draft can be submitted for review.")
        await claim_status(
            self.db,
            article,
            expected=(ArticleStatus.DRAFT,),
            to=ArticleStatus.SUBMITTED_FOR_REVIEW,
            conflict="Only a draft can be submitted for review.",
        )
        return await self._transition(
            article, status=ArticleStatus.SUBMITTED_FOR_REVIEW, event=RevisionEvent.SUBMIT
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
        await claim_status(
            self.db,
            article,
            expected=(ArticleStatus.SUBMITTED_FOR_REVIEW,),
            to=ArticleStatus.PUBLISHED,
            conflict="Only a submitted article can be approved.",
        )
        article.published_data = article.draft_data
        # Spent, exactly as in `publish`: approving *is* publishing, so a
        # reviewer who acts before the scheduled moment must not leave a date
        # behind that outlives their decision.
        article.publish_at = None
        # Same reasoning as `publish`: a still-future `unpublish_at` is kept,
        # an already-elapsed one is a leftover that would take the article
        # straight back down on the next tick.
        if _elapsed(article.unpublish_at, datetime.now(UTC)):
            article.unpublish_at = None
        return await self._transition(
            article, status=ArticleStatus.PUBLISHED, event=RevisionEvent.APPROVE
        )

    async def reject(self, article_id: int, note: str | None = None) -> NewsArticle:
        article = await self.get_article(article_id)
        if article.status is not ArticleStatus.SUBMITTED_FOR_REVIEW:
            raise HTTPException(
                status_code=409, detail="Only a submitted article can be rejected."
            )
        await claim_status(
            self.db,
            article,
            expected=(ArticleStatus.SUBMITTED_FOR_REVIEW,),
            to=ArticleStatus.DRAFT,
            conflict="Only a submitted article can be rejected.",
        )
        # A schedule set before submission must not survive the rejection —
        # otherwise the next `process_due` tick auto-publishes the very
        # article a reviewer just turned back, once its stale `publish_at`
        # arrives.
        article.publish_at = None
        # An elapsed `unpublish_at` would otherwise sit inert (process_due only
        # unpublishes what is PUBLISHED) until a later publish/approve, and
        # then take the article straight back down.
        if _elapsed(article.unpublish_at, datetime.now(UTC)):
            article.unpublish_at = None
        return await self._transition(
            article,
            status=ArticleStatus.DRAFT,
            event=RevisionEvent.REJECT,
            note=note,
        )
