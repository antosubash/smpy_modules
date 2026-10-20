"""What the tick does with a row it cannot flip (#108).

``process_due`` swallowed ``HTTPException`` and moved on with no logging at all.
A page whose scheduled moment came and went left no trace — not in the row and
not in the log. Skipping is still right: one bad row must not stop the tick, so
the other due pages have to flip either way. What changed is that the skip says
so, and that its claim is handed back so a later tick retries.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from fastapi import HTTPException
from page_helpers import EARLIER, NOW, make_page
from pagebuilder.models import Page, PageStatus
from pagebuilder.service import PagesService

pytestmark = pytest.mark.asyncio

LOGGER = "pagebuilder.service._workflow"


async def _live(db, slug: str) -> Page:
    return await make_page(
        db, slug, status=PageStatus.PUBLISHED, published_data={}, unpublish_at=EARLIER
    )


def _fail_on(monkeypatch, method: str, page_id: int, *, detail: str) -> None:
    """Make one transition raise for one page, the way a lost race would.

    The realistic cause is another process purging the row between this tick's
    claim and its ``publish`` — ``get_page`` then 404s. Patched rather than
    staged because the two would have to interleave inside one call.
    """
    real = getattr(PagesService, method)

    async def flaky(self, target_id: int, note: str | None = None, **kw):
        if target_id == page_id:
            raise HTTPException(status_code=404, detail=detail)
        return await real(self, target_id, note=note, **kw)

    monkeypatch.setattr(PagesService, method, flaky)


def _only_warning(caplog) -> logging.LogRecord:
    warnings = [r for r in caplog.records if r.name == LOGGER and r.levelno == logging.WARNING]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    return warnings[0]


class TestABadRow:
    async def test_a_failing_publish_is_logged_and_the_tick_continues(
        self, db, caplog, monkeypatch
    ) -> None:
        bad = await make_page(db, "wont-go", publish_at=EARLIER)
        good = await make_page(db, "will-go", publish_at=EARLIER)
        _fail_on(monkeypatch, "publish", bad.id, detail="Page not found")

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            flipped = await PagesService(db).process_due(NOW)

        assert [p.id for p in flipped] == [good.id]
        record = _only_warning(caplog)
        # The id has to be *in the line*, not only in the structured extra: a
        # host with a plain formatter is the common case.
        assert str(bad.id) in record.getMessage()
        assert "Page not found" in record.getMessage()
        assert record.page_id == bad.id

    async def test_a_failing_unpublish_is_logged_and_the_tick_continues(
        self, db, caplog, monkeypatch
    ) -> None:
        bad = await _live(db, "wont-come-down")
        good = await _live(db, "will-come-down")
        _fail_on(monkeypatch, "unpublish", bad.id, detail="Page not found")

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            flipped = await PagesService(db).process_due(NOW)

        assert [p.id for p in flipped] == [good.id]
        record = _only_warning(caplog)
        assert str(bad.id) in record.getMessage()
        assert record.page_id == bad.id

    async def test_a_tick_with_nothing_wrong_stays_quiet(self, db, caplog) -> None:
        """Otherwise the warning is noise and gets filtered out again."""
        await make_page(db, "fine", publish_at=EARLIER)

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            await PagesService(db).process_due(NOW)

        assert [r for r in caplog.records if r.name == LOGGER] == []

    async def test_a_retired_window_is_logged(self, db, caplog) -> None:
        await make_page(
            db, "missed", publish_at=EARLIER - timedelta(hours=1), unpublish_at=EARLIER
        )

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            assert await PagesService(db).process_due(NOW) == []

        assert "window_missed count=1" in _only_warning(caplog).getMessage()
