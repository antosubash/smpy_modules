"""Publishing that happens without anyone pressing anything.

A future-dated article used to be labelled "scheduled" and then sit as a draft
until a human published it by hand — the label was a description of the display
date, not a mechanism. Pagebuilder had had real scheduling for a while; news had
the word.

``process_due`` is driven directly with a fake ``now`` rather than by waiting on
the loop, which is one ``asyncio.sleep`` around exactly this call.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from factories import make_article
from news.content import ArticlesService
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=1)
LATER = NOW + timedelta(hours=1)
MUCH_LATER = NOW + timedelta(hours=2)


class TestScheduling:
    async def test_a_due_draft_goes_live(self, db) -> None:
        article = await make_article(
            db, slug="embargoed", status=ArticleStatus.DRAFT, publish_body=False
        )
        service = ArticlesService(db)
        await service.schedule(article.id, publish_at=EARLIER)

        flipped = await service.process_due(NOW)

        assert [a.id for a in flipped] == [article.id]
        await db.refresh(article)
        assert article.status is ArticleStatus.PUBLISHED

    async def test_publishing_snapshots_the_draft(self, db) -> None:
        # The scheduler goes through `publish`, so an article that goes live on
        # a timer has to be served the same body one published by hand would be.
        article = await make_article(
            db,
            slug="snapshot",
            status=ArticleStatus.DRAFT,
            draft_data={"content": ["written"]},
            publish_body=False,
        )
        service = ArticlesService(db)
        await service.schedule(article.id, publish_at=EARLIER)

        await service.process_due(NOW)

        await db.refresh(article)
        assert article.published_data == {"content": ["written"]}

    async def test_a_draft_not_yet_due_stays_a_draft(self, db) -> None:
        article = await make_article(
            db, slug="next-week", status=ArticleStatus.DRAFT, publish_body=False
        )
        service = ArticlesService(db)
        await service.schedule(article.id, publish_at=LATER)

        assert await service.process_due(NOW) == []
        await db.refresh(article)
        assert article.status is ArticleStatus.DRAFT

    async def test_a_due_article_comes_down(self, db) -> None:
        article = await make_article(db, slug="expired")
        service = ArticlesService(db)
        await service.schedule(article.id, unpublish_at=EARLIER)

        await service.process_due(NOW)

        await db.refresh(article)
        assert article.status is ArticleStatus.DRAFT

    async def test_the_timestamp_is_spent_once_acted_on(self, db) -> None:
        """Otherwise every tick republishes the same article, forever."""
        article = await make_article(
            db, slug="once", status=ArticleStatus.DRAFT, publish_body=False
        )
        service = ArticlesService(db)
        await service.schedule(article.id, publish_at=EARLIER)

        await service.process_due(NOW)
        await db.refresh(article)
        assert article.publish_at is None

        # A second tick has nothing left to do.
        assert await service.process_due(NOW + timedelta(minutes=1)) == []

    async def test_publishing_by_hand_also_clears_a_pending_schedule(self, db) -> None:
        # Otherwise the article is published now *and* again at the scheduled
        # time, gaining a second revision row that says so.
        article = await make_article(
            db, slug="jumped", status=ArticleStatus.DRAFT, publish_body=False
        )
        service = ArticlesService(db)
        await service.schedule(article.id, publish_at=LATER)

        await service.publish(article.id)

        await db.refresh(article)
        assert article.publish_at is None

    async def test_a_trashed_article_does_not_publish_itself(self, db) -> None:
        # An article binned while carrying a schedule must not climb back out.
        article = await make_article(
            db, slug="binned", status=ArticleStatus.DRAFT, publish_body=False
        )
        service = ArticlesService(db)
        await service.schedule(article.id, publish_at=EARLIER)
        await service.trash(article.id)

        assert await service.process_due(NOW) == []

    async def test_a_missed_window_catches_up_rather_than_being_lost(self, db) -> None:
        # A process asleep for an hour must still publish what fell due while it
        # was down: the query is "<= now", not "in the last tick".
        article = await make_article(
            db, slug="catch-up", status=ArticleStatus.DRAFT, publish_body=False
        )
        service = ArticlesService(db)
        await service.schedule(article.id, publish_at=NOW - timedelta(days=3))

        assert len(await service.process_due(NOW)) == 1


class TestClearing:
    async def test_an_omitted_field_is_left_alone(self, db) -> None:
        article = await make_article(db, slug="partial", status=ArticleStatus.DRAFT)
        service = ArticlesService(db)
        await service.schedule(article.id, publish_at=LATER, unpublish_at=MUCH_LATER)

        await service.schedule(article.id, publish_at=NOW)

        await db.refresh(article)
        assert article.unpublish_at is not None

    async def test_an_explicit_none_cancels(self, db) -> None:
        # Cancelling a schedule is a real instruction, and has to be spellable.
        article = await make_article(db, slug="cancelled", status=ArticleStatus.DRAFT)
        service = ArticlesService(db)
        await service.schedule(article.id, publish_at=LATER)

        await service.schedule(article.id, publish_at=None)

        await db.refresh(article)
        assert article.publish_at is None


class TestApprovalAndRetraction:
    """The chain that used to put a retracted article back in front of readers.

    ``approve`` publishes, so it has to spend a pending ``publish_at`` the way
    ``publish`` does — and ``unpublish`` has to spend one too, because it leaves
    the article a DRAFT, which is exactly the shape ``process_due`` hunts for.
    """

    async def test_approving_early_clears_a_pending_schedule(self, db) -> None:
        article = await make_article(
            db, slug="approved-early", status=ArticleStatus.DRAFT, publish_body=False
        )
        service = ArticlesService(db)
        await service.schedule(article.id, publish_at=LATER)
        await service.submit_for_review(article.id)

        await service.approve(article.id)

        await db.refresh(article)
        assert article.status is ArticleStatus.PUBLISHED
        assert article.publish_at is None

    async def test_unpublishing_clears_one_too(self, db) -> None:
        article = await make_article(db, slug="pulled")
        service = ArticlesService(db)
        await service.schedule(article.id, publish_at=LATER)

        await service.unpublish(article.id)

        await db.refresh(article)
        assert article.publish_at is None

    async def test_a_retraction_is_not_undone_by_the_schedule_before_it(
        self, db
    ) -> None:
        """Scheduled, approved early, then deliberately taken down.

        Every step is something a person did on purpose, and the last one has to
        stick: without both clears the next tick after ``LATER`` found a DRAFT
        with a due ``publish_at`` and served the article again, hours after a
        human pulled it and with nothing in the UI to say why.
        """
        article = await make_article(
            db, slug="retracted", status=ArticleStatus.DRAFT, publish_body=False
        )
        service = ArticlesService(db)
        await service.schedule(article.id, publish_at=LATER)
        await service.submit_for_review(article.id)
        await service.approve(article.id)

        await service.unpublish(article.id)

        assert await service.process_due(LATER + timedelta(minutes=1)) == []
        await db.refresh(article)
        assert article.status is ArticleStatus.DRAFT


class TestTheEndpoint:
    async def test_an_author_without_publish_is_refused(self, author_client) -> None:
        # A schedule is a publication decision that happens to be about the
        # future; a host gating publishing would be surprised to find an author
        # could arrange one for tomorrow instead.
        article = await make_article_via(author_client, "gated")

        response = await author_client.post(
            f"/api/news/articles/{article}/schedule",
            json={"publish_at": LATER.isoformat()},
        )

        assert response.status_code == 403, response.text

    async def test_a_publisher_can_schedule(self, editor_client) -> None:
        article = await make_article_via(editor_client, "allowed")

        response = await editor_client.post(
            f"/api/news/articles/{article}/schedule",
            json={"publish_at": LATER.isoformat()},
        )

        assert response.status_code == 200, response.text

    async def test_scheduling_does_not_publish_by_itself(self, editor_client) -> None:
        # The flip happens when the time arrives, not when it is arranged.
        article = await make_article_via(editor_client, "future")

        await editor_client.post(
            f"/api/news/articles/{article}/schedule",
            json={"publish_at": LATER.isoformat()},
        )

        listed = (await editor_client.get("/api/news/articles?q=future")).json()
        assert listed["items"][0]["status"] == "draft"


async def make_article_via(client, slug: str) -> int:
    async with client.db_state.session_factory() as db:
        article = await make_article(db, slug=slug, status=ArticleStatus.DRAFT)
        return article.id
