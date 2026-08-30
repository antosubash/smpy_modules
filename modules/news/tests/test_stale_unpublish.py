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
