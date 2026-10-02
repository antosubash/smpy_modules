"""What the tick does with a row it cannot flip.

``process_due`` swallowed ``HTTPException`` and moved on with no logging at all,
and the file had no logger. An article whose scheduled moment came and went left
no trace anywhere — not in the row, which still reads DRAFT with a schedule that
looks spent, and not in the log. The first anyone heard of it was a reader asking
why the piece never appeared.

Skipping is still right: one bad row must not stop the tick, so the other due
articles below have to go live either way. What changed is that the skip says so.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from factories import make_article
from fastapi import HTTPException
from news.content import ArticlesService
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio

LOGGER = "news.content._workflow"
NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=1)


def _fail_on(monkeypatch, method: str, article_id: int, *, detail: str) -> None:
    """Make one transition raise for one article, the way a lost race would.

    The realistic cause is another process purging or binning the row between
    this tick's ``SELECT`` and its ``publish`` — ``get_article`` then 404s. It
    is patched rather than staged because the two would have to interleave
    inside one ``process_due`` call to reproduce it honestly.
    """
    real = getattr(ArticlesService, method)

    async def flaky(self, target_id: int):
        if target_id == article_id:
            raise HTTPException(status_code=404, detail=detail)
        return await real(self, target_id)

    monkeypatch.setattr(ArticlesService, method, flaky)


def _only_warning(caplog) -> logging.LogRecord:
    warnings = [
        r for r in caplog.records if r.name == LOGGER and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    return warnings[0]


class TestABadRow:
    async def test_a_failing_publish_is_logged_and_the_tick_continues(
        self, db, caplog, monkeypatch
    ) -> None:
        bad = await make_article(
            db, slug="wont-go", status=ArticleStatus.DRAFT, publish_body=False
        )
        good = await make_article(
            db, slug="will-go", status=ArticleStatus.DRAFT, publish_body=False
        )
        service = ArticlesService(db)
        await service.schedule(bad.id, publish_at=EARLIER)
        await service.schedule(good.id, publish_at=EARLIER)
        _fail_on(monkeypatch, "publish", bad.id, detail="Article not found")

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            flipped = await service.process_due(NOW)

        assert [a.id for a in flipped] == [good.id]
        record = _only_warning(caplog)
        # The id has to be *in the line*, not only in the structured extra: a
        # host with a plain formatter is the common case, and "something was
        # skipped" without saying which article is not actionable.
        assert str(bad.id) in record.getMessage()
        assert "Article not found" in record.getMessage()
        assert record.article_id == bad.id

    async def test_a_failing_unpublish_is_logged_and_the_tick_continues(
        self, db, caplog, monkeypatch
    ) -> None:
        bad = await make_article(db, slug="wont-come-down")
        good = await make_article(db, slug="will-come-down")
        service = ArticlesService(db)
        await service.schedule(bad.id, unpublish_at=EARLIER)
        await service.schedule(good.id, unpublish_at=EARLIER)
        _fail_on(monkeypatch, "unpublish", bad.id, detail="Article not found")

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            flipped = await service.process_due(NOW)

        assert [a.id for a in flipped] == [good.id]
        record = _only_warning(caplog)
        assert str(bad.id) in record.getMessage()
        assert record.article_id == bad.id

    async def test_a_tick_with_nothing_wrong_stays_quiet(
        self, db, caplog
    ) -> None:
        """Otherwise the warning is noise and gets filtered out again."""
        article = await make_article(
            db, slug="fine", status=ArticleStatus.DRAFT, publish_body=False
        )
        await ArticlesService(db).schedule(article.id, publish_at=EARLIER)

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            await ArticlesService(db).process_due(NOW)

        assert [r for r in caplog.records if r.name == LOGGER] == []
