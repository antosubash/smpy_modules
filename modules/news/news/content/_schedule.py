"""Setting an article's publication window, without changing its status."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException

from news.content._trash import TrashMixin
from news.core.naive_utc import as_utc
from news.models import NewsArticle

_UNSET: Any = object()
"""Sentinel for "the caller did not mention this field".

``schedule`` has to tell an omitted argument from an explicit ``None``:
cancelling a schedule is a real instruction, and ``None`` is how it is spelt.
"""


class ScheduleMixin(TrashMixin):
    """Publication-window writes used by the workflow service."""

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
