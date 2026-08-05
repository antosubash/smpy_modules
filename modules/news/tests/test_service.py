"""Service-level behaviour: the read-back, partial updates, and reconciliation.

These sit between ``test_models.py`` (which pins the table's shape) and the
Playwright suite (which drives a browser). Everything tested here was
previously covered by neither, which is why three of these cases describe bugs
that shipped.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import make_page
from news import service
from news.constants import MAX_LIMIT
from news.models import NewsArticle
from pagebuilder.models import Page, PageStatus
from sqlalchemy import delete as sa_delete
from sqlmodel import select

pytestmark = pytest.mark.asyncio

DATED = datetime(2026, 2, 1, tzinfo=UTC)


class TestReadBackByPage:
    async def test_finds_a_newly_attached_article(self, db) -> None:
        page = await make_page(db, slug="solo", title="Solo")
        await service.create(db, page_id=page.id, category="News", published_at=None)

        found = await service.get_read_by_page(db, page.id)

        assert found is not None
        assert found.page_id == page.id
        assert found.title == "Solo"
        assert found.url == "/p/solo"

    async def test_finds_an_undated_article_behind_a_full_page_of_dated_ones(
        self, db
    ) -> None:
        """The bug this replaces: reading back by scanning the first page.

        A new article is undated, and the listing sorts `published_at DESC NULLS
        LAST`, so undated articles come after every dated one. Scanning the
        first MAX_LIMIT rows therefore could not find it once that many dated
        articles existed — POST returned 404 for a row it had just written.
        """
        for i in range(MAX_LIMIT):
            dated = await make_page(db, slug=f"dated-{i}", title=f"Dated {i}")
            await service.create(
                db, page_id=dated.id, category="Archive", published_at=DATED
            )

        fresh = await make_page(db, slug="fresh", title="Fresh")
        await service.create(db, page_id=fresh.id, category="News", published_at=None)

        # It is genuinely past the first page — that is the point of the setup.
        first_page, total = await service.list_articles(db, limit=MAX_LIMIT)
        assert total == MAX_LIMIT + 1
        assert fresh.id not in {item.page_id for item in first_page}

        found = await service.get_read_by_page(db, fresh.id)
        assert found is not None, "a just-written article must be readable back"
        assert found.title == "Fresh"

    async def test_returns_none_when_the_page_is_gone(self, db) -> None:
        page = await make_page(db, slug="doomed")
        await service.create(db, page_id=page.id, category="", published_at=None)
        await db.execute(sa_delete(Page).where(Page.id == page.id))
        await db.commit()

        assert await service.get_read_by_page(db, page.id) is None

    async def test_hides_a_draft_unless_drafts_are_asked_for(self, db) -> None:
        page = await make_page(db, slug="wip", status=PageStatus.DRAFT)
        await service.create(db, page_id=page.id, category="", published_at=None)

        assert await service.get_read_by_page(db, page.id, include_drafts=False) is None
        assert await service.get_read_by_page(db, page.id, include_drafts=True) is not None


class TestPartialUpdate:
    async def test_omitting_published_at_leaves_the_date_alone(self, db) -> None:
        """`UNSET` is the default, so a caller that says nothing changes nothing."""
        page = await make_page(db, slug="dated")
        article = await service.create(
            db, page_id=page.id, category="Before", published_at=DATED
        )

        await service.update(db, article, category="After")

        assert article.category == "After"
        assert article.published_at is not None
        assert article.published_at.replace(tzinfo=UTC) == DATED

    async def test_explicit_none_undates_the_article(self, db) -> None:
        # An undated article is a real state, not an error — this has to stay
        # reachable, which is why the sentinel exists rather than a truthiness
        # test.
        page = await make_page(db, slug="undate-me")
        article = await service.create(
            db, page_id=page.id, category="News", published_at=DATED
        )

        await service.update(db, article, published_at=None)

        assert article.published_at is None
        assert article.category == "News"

    async def test_omitting_category_leaves_it_alone(self, db) -> None:
        page = await make_page(db, slug="keep-category")
        article = await service.create(
            db, page_id=page.id, category="Events", published_at=None
        )

        await service.update(db, article, published_at=DATED)

        assert article.category == "Events"


class TestWritesDoNotCommit:
    """The service flushes; the caller owns the transaction.

    Committing inside the service is what let a failed endpoint leave a durable
    row behind, and it is inconsistent with every other service in the repo.
    """

    async def test_create_is_rolled_back_by_its_caller(self, db) -> None:
        page = await make_page(db, slug="rollback")
        await service.create(db, page_id=page.id, category="Ghost", published_at=None)

        await db.rollback()

        remaining = (await db.execute(select(NewsArticle))).scalars().all()
        assert remaining == []

    async def test_delete_is_rolled_back_by_its_caller(self, db) -> None:
        page = await make_page(db, slug="undelete")
        # Held as a plain int: the commit below expires the ORM instance, and
        # reading `page.id` afterwards would trigger a lazy refresh from sync
        # context.
        page_id = page.id
        article = await service.create(
            db, page_id=page_id, category="Keep", published_at=None
        )
        await db.commit()

        await service.delete(db, article)
        await db.rollback()

        assert await service.get_by_page(db, page_id) is not None


class TestReconcileOrphans:
    async def _orphan(self, db) -> int:
        """An article whose page was deleted without the event firing."""
        page = await make_page(db, slug="vanished")
        await service.create(db, page_id=page.id, category="Stale", published_at=None)
        await db.commit()
        await db.execute(sa_delete(Page).where(Page.id == page.id))
        await db.commit()
        return page.id

    async def test_deletes_a_row_whose_page_is_gone(self, db) -> None:
        page_id = await self._orphan(db)
        assert await service.get_by_page(db, page_id) is not None

        dropped = await service.reconcile_orphans(db)
        await db.commit()

        assert dropped == 1
        assert await service.get_by_page(db, page_id) is None

    async def test_leaves_a_row_whose_page_exists(self, db) -> None:
        page = await make_page(db, slug="alive")
        await service.create(db, page_id=page.id, category="Live", published_at=None)
        await db.commit()

        assert await service.reconcile_orphans(db) == 0
        assert await service.get_by_page(db, page.id) is not None

    async def test_leaves_an_article_on_a_draft_page(self, db) -> None:
        # A draft page is not a missing page. Sweeping it would delete an
        # editor's unpublished work.
        page = await make_page(db, slug="draft", status=PageStatus.DRAFT)
        await service.create(db, page_id=page.id, category="", published_at=None)
        await db.commit()

        assert await service.reconcile_orphans(db) == 0
        assert await service.get_by_page(db, page.id) is not None

    async def test_an_orphan_is_invisible_to_the_listing_before_the_sweep(
        self, db
    ) -> None:
        # The inner join is what makes the orphan harmless in the meantime; the
        # sweep is what stops SQLite's id reuse from making it harmful later.
        await self._orphan(db)

        items, total = await service.list_articles(db, include_drafts=True)

        assert items == []
        assert total == 0

    async def test_is_idempotent(self, db) -> None:
        await self._orphan(db)
        assert await service.reconcile_orphans(db) == 1
        await db.commit()
        assert await service.reconcile_orphans(db) == 0

    async def test_the_startup_hook_runs_and_commits_the_sweep(
        self, db, db_state
    ) -> None:
        """`on_startup` is the only thing that calls this in production.

        Wiring it wrong — not committing, or never registering the hook — would
        leave the sweep as dead code with every other test still green.
        """
        from types import SimpleNamespace

        from fastapi import FastAPI
        from news.module import NewsModule

        page_id = await self._orphan(db)

        app = FastAPI()
        app.state.sm = SimpleNamespace(db=db_state)
        await NewsModule().on_startup(app)

        # A fresh session, so this reads committed state rather than `db`'s
        # identity map.
        async with db_state.session_factory() as fresh:
            assert await service.get_by_page(fresh, page_id) is None
