"""Pinning, feed visibility and the byline — the Article tab's own fields.

Each of these is a rule about *ordering or omission* rather than about storage,
which is why they are asserted through the listing rather than by reading the
row back: a field that saves correctly but does not change what the feed shows
has not done its job.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import make_article
from news import service, tag_service

pytestmark = pytest.mark.asyncio

OLD = datetime(2026, 1, 1, tzinfo=UTC)
NEW = datetime(2026, 6, 1, tzinfo=UTC)


async def _article(db, slug: str, **kwargs):
    return await make_article(db, slug=slug, title=slug, **kwargs)


class TestPinning:
    async def test_a_pinned_article_leads_the_public_order(self, db) -> None:
        await _article(db, "newest", published_at=NEW)
        old = await _article(db, "oldest", published_at=OLD)
        await service.update(db, old, pinned=True)

        items, _ = await service.list_articles(db)

        assert [i.slug for i in items] == ["oldest", "newest"]

    async def test_pinning_does_not_rewrite_the_date(self, db) -> None:
        """The whole reason it sorts separately: unpin it and the archive still
        reads correctly."""
        old = await _article(db, "held", published_at=OLD)

        await service.update(db, old, pinned=True)

        items, _ = await service.list_articles(db)
        # Compared naively: SQLite stores the instant without its offset, so
        # the round trip drops the tzinfo. What matters here is that the value
        # is untouched, not how the driver represents it.
        assert items[0].published_at.replace(tzinfo=UTC) == OLD

    async def test_the_admin_order_still_leads_with_work_in_progress(self, db) -> None:
        """An editor came to finish the undated row, not to read the pins."""
        pinned = await _article(db, "pinned", published_at=NEW)
        await service.update(db, pinned, pinned=True)
        await _article(db, "undated", published_at=None)

        items, _ = await service.list_articles(db, undated_first=True)

        assert items[0].slug == "undated"


class TestFeedVisibility:
    async def test_it_defaults_to_visible(self, db) -> None:
        """Anything else would silently empty every feed on upgrade."""
        article = await _article(db, "a")

        assert article.show_in_feed is True

    async def test_hiding_removes_it_from_the_feed(self, db) -> None:
        hidden = await _article(db, "hidden", published_at=NEW)
        await _article(db, "shown", published_at=OLD)
        await service.update(db, hidden, show_in_feed=False)

        items, total = await service.list_articles(db, in_feed_only=True)

        assert [i.slug for i in items] == ["shown"]
        assert total == 1

    async def test_the_admin_list_still_shows_it(self, db) -> None:
        """Otherwise it is unreachable from the one screen that could un-hide it."""
        hidden = await _article(db, "hidden", published_at=NEW)
        await service.update(db, hidden, show_in_feed=False)

        items, _ = await service.list_articles(db)

        assert [i.slug for i in items] == ["hidden"]


class TestByline:
    async def test_it_round_trips(self, db) -> None:
        article = await _article(db, "credited", author="J. Okonkwo")

        items, _ = await service.list_articles(db)

        assert items[0].author == "J. Okonkwo"
        assert article.author == "J. Okonkwo"

    async def test_it_can_be_changed_later(self, db) -> None:
        article = await _article(db, "recredited", author="Draft byline")

        await service.update(db, article, author="Mira Halvorsen")

        items, _ = await service.list_articles(db)
        assert items[0].author == "Mira Halvorsen"


class TestTagsOnTheArticle:
    async def test_setting_tags_reads_back_in_order(self, db) -> None:
        article = await _article(db, "tagged")

        await tag_service.set_for_article(db, article.id, ["urban", "canopy"])

        assert await tag_service.list_for_article(db, article.id) == ["canopy", "urban"]

    async def test_clearing_tags_leaves_none(self, db) -> None:
        article = await _article(db, "untagged")
        await tag_service.set_for_article(db, article.id, ["canopy"])

        await tag_service.set_for_article(db, article.id, [])

        assert await tag_service.list_for_article(db, article.id) == []
