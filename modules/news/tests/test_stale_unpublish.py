"""A schedule can carry an ``unpublish_at`` that elapses before anyone acts on
``publish_at`` — a reviewer sits on a submission, or an author publishes by
hand instead of waiting for the scheduled moment.

``publish``/``approve``/``reject`` already spend a pending ``publish_at`` they
did not go through ``process_due`` to reach; they have to spend a *stale*
``unpublish_at`` the same way, or the article is taken straight back down on
the very next tick. A genuinely future ``unpublish_at`` is a real "take it
down later" instruction and has to survive — that is still what
``process_due`` is for.

Its own file rather than a class in ``test_scheduled_publish.py`` because that
file is already at the line cap.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from factories import make_article
from news.content import ArticlesService
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio


async def test_publishing_by_hand_clears_an_elapsed_unpublish_at(db) -> None:
    article = await make_article(
        db, slug="stale-unpublish", status=ArticleStatus.DRAFT, publish_body=False
    )
    service = ArticlesService(db)
    await service.schedule(article.id, unpublish_at=datetime.now(UTC) - timedelta(hours=1))

    await service.publish(article.id)

    await db.refresh(article)
    assert article.unpublish_at is None


async def test_publishing_by_hand_keeps_a_future_unpublish_at(db) -> None:
    article = await make_article(
        db, slug="future-unpublish", status=ArticleStatus.DRAFT, publish_body=False
    )
    service = ArticlesService(db)
    future = datetime.now(UTC) + timedelta(days=1)
    await service.schedule(article.id, unpublish_at=future)

    await service.publish(article.id)

    await db.refresh(article)
    assert article.unpublish_at is not None
    assert article.unpublish_at.replace(tzinfo=UTC) == future


async def test_approving_clears_an_elapsed_unpublish_at(db) -> None:
    article = await make_article(
        db, slug="approve-stale-unpublish", status=ArticleStatus.DRAFT, publish_body=False
    )
    service = ArticlesService(db)
    await service.schedule(article.id, unpublish_at=datetime.now(UTC) - timedelta(hours=1))
    await service.submit_for_review(article.id)

    await service.approve(article.id)

    await db.refresh(article)
    assert article.unpublish_at is None


async def test_rejecting_clears_an_elapsed_unpublish_at(db) -> None:
    article = await make_article(
        db, slug="reject-stale-unpublish", status=ArticleStatus.DRAFT, publish_body=False
    )
    service = ArticlesService(db)
    await service.schedule(article.id, unpublish_at=datetime.now(UTC) - timedelta(hours=1))
    await service.submit_for_review(article.id)

    await service.reject(article.id)

    await db.refresh(article)
    assert article.unpublish_at is None


async def test_a_window_that_passed_unseen_is_retired_not_published(db) -> None:
    """Both times passed while no scheduler ran. The author's last word was that
    the article is off the site by now, so it must not go live — and must not
    stay live forever, which is what publishing it and then clearing the
    elapsed ``unpublish_at`` as a leftover would do."""
    now = datetime.now(UTC)
    missed = await make_article(
        db, slug="missed", status=ArticleStatus.DRAFT, publish_body=False
    )
    still_open = await make_article(
        db, slug="still-open", status=ArticleStatus.DRAFT, publish_body=False
    )
    service = ArticlesService(db)
    await service.schedule(
        missed.id, publish_at=now - timedelta(hours=3), unpublish_at=now - timedelta(hours=1)
    )
    await service.schedule(
        still_open.id, publish_at=now - timedelta(hours=3), unpublish_at=now + timedelta(hours=1)
    )

    flipped = await service.process_due(now)

    assert [a.id for a in flipped] == [still_open.id]
    await db.refresh(missed)
    assert missed.status is ArticleStatus.DRAFT
    assert missed.publish_at is None and missed.unpublish_at is None


async def test_a_tick_that_flips_nothing_still_persists_a_retired_window(db_state) -> None:
    """``Scheduler.tick`` used to roll back unless something flipped, which
    discarded ``retire_missed_windows``' write: the row was found, warned about
    and rolled back again on every interval."""
    from news.scheduler import Scheduler

    factory = db_state.session_factory
    now = datetime.now(UTC)
    async with factory() as db:
        missed = await make_article(
            db, slug="missed-tick", status=ArticleStatus.DRAFT, publish_body=False
        )
        service = ArticlesService(db)
        await service.schedule(missed.id, publish_at=now - timedelta(hours=3))
        await service.schedule(missed.id, unpublish_at=now - timedelta(hours=1))
        await db.commit()
        article_id = missed.id

    await Scheduler().tick(factory)

    async with factory() as db:
        row = await ArticlesService(db).get_article(article_id)
        assert row.status is ArticleStatus.DRAFT
        assert row.publish_at is None and row.unpublish_at is None
