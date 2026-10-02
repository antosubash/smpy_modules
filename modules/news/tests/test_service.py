"""Service-level behaviour: the read-back, partial updates, and transactions.

These sit between ``test_models.py`` (which pins the table's shape) and the
Playwright suite (which drives a browser).

The whole ``TestReconcileOrphans`` class that used to live here is gone, and
deliberately so. It covered a failure mode the sidecar created: an article row
pointed at a ``pagebuilder_pages`` id with no foreign key behind it, so deleting
the page left a row that SQLite would silently re-attach to whatever page took
the id next. An article's body is a column on its own row now, so there is no
second row whose disappearance could orphan it and nothing left to reconcile.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from factories import make_article
from news import service
from news.constants import MAX_LIMIT
from news.content import ArticlesService
from news.models import ArticleStatus, NewsArticle
from sqlmodel import select

pytestmark = pytest.mark.asyncio

DATED = datetime(2026, 2, 1, tzinfo=UTC)


class TestReadBack:
    async def test_finds_a_newly_created_article(self, db) -> None:
        article = await ArticlesService(db).create(title="Solo", category="News")

        found = await service.get_read(db, article.id)

        assert found is not None
        assert found.id == article.id
        assert found.title == "Solo"
        assert found.slug == "solo"
        assert found.url == "/news/solo"

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
            await make_article(
                db, slug=f"dated-{i}", title=f"Dated {i}", category="Archive",
                published_at=DATED,
            )

        fresh = await ArticlesService(db).create(title="Fresh", category="News")
        await db.commit()

        # It is genuinely past the first page — that is the point of the setup.
        first_page, total = await service.list_articles(
            db, limit=MAX_LIMIT, include_drafts=True
        )
        assert total == MAX_LIMIT + 1
        assert fresh.id not in {item.id for item in first_page}

        found = await service.get_read(db, fresh.id)
        assert found is not None, "a just-written article must be readable back"
        assert found.title == "Fresh"

    async def test_returns_none_for_an_id_that_never_existed(self, db) -> None:
        assert await service.get_read(db, 4242) is None

    async def test_hides_a_draft_unless_drafts_are_asked_for(self, db) -> None:
        article = await make_article(db, slug="wip", status=ArticleStatus.DRAFT)

        assert await service.get_read(db, article.id, include_drafts=False) is None
        assert await service.get_read(db, article.id, include_drafts=True) is not None

    async def test_hides_a_trashed_article_from_everyone(self, db) -> None:
        """Trash is not a status — an editor who may see drafts still must not
        see something they binned sitting in the list."""
        article = await make_article(db, slug="binned")
        await ArticlesService(db).trash(article.id)
        await db.commit()

        assert await service.get_read(db, article.id, include_drafts=True) is None


class TestSkippingTheCount:
    """``with_total=False`` — for the callers with no pager to feed.

    The RSS feed takes a fixed window and discards the total, so counting the
    archive behind it was a second full scan per request for a number nothing
    read.
    """

    async def test_the_rows_are_the_same_ones(self, db) -> None:
        for i in range(3):
            await make_article(db, slug=f"counted-{i}", published_at=DATED)

        counted, total = await service.list_articles(db)
        uncounted, skipped = await service.list_articles(db, with_total=False)

        assert [item.id for item in uncounted] == [item.id for item in counted]
        assert total == 3
        assert skipped == 0

    async def test_paging_still_reports_the_real_total(self, db) -> None:
        # The default has to stay honest — every paged caller counts against it.
        for i in range(3):
            await make_article(db, slug=f"paged-{i}", published_at=DATED)

        page, total = await service.list_articles(db, limit=2)

        assert len(page) == 2
        assert total == 3


class TestPartialUpdate:
    async def test_omitting_published_at_leaves_the_date_alone(self, db) -> None:
        """`UNSET` is the default, so a caller that says nothing changes nothing."""
        article = await make_article(
            db, slug="dated", category="Before", published_at=DATED
        )

        await service.update(db, article, category="After")

        assert article.category == "After"
        assert article.published_at is not None
        assert article.published_at.replace(tzinfo=UTC) == DATED

    async def test_explicit_none_undates_the_article(self, db) -> None:
        # An undated article is a real state, not an error — this has to stay
        # reachable, which is why the sentinel exists rather than a truthiness
        # test.
        article = await make_article(
            db, slug="undate-me", category="News", published_at=DATED
        )

        await service.update(db, article, published_at=None)

        assert article.published_at is None
        assert article.category == "News"

    async def test_omitting_category_leaves_it_alone(self, db) -> None:
        article = await make_article(db, slug="keep-category", category="Events")

        await service.update(db, article, published_at=DATED)

        assert article.category == "Events"


class TestWritesDoNotCommit:
    """The service flushes; the caller owns the transaction.

    Committing inside the service is what let a failed endpoint leave a durable
    row behind, and it is inconsistent with every other service in the repo.
    """

    async def test_create_is_rolled_back_by_its_caller(self, db) -> None:
        await ArticlesService(db).create(title="Ghost", category="Ghost")

        await db.rollback()

        remaining = (await db.execute(select(NewsArticle))).scalars().all()
        assert remaining == []

    async def test_delete_is_rolled_back_by_its_caller(self, db) -> None:
        article = await make_article(db, slug="undelete", category="Keep")
        # Held as a plain int: the commit below expires the ORM instance, and
        # reading `article.id` afterwards would trigger a lazy refresh from sync
        # context.
        article_id = article.id

        await service.delete(db, article)
        await db.rollback()

        assert await service.get(db, article_id) is not None
