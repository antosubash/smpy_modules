"""The claim's two edges a single shared session cannot stage: which tenant a
claim can reach, and — on Postgres — two genuinely concurrent ticks.

Ported from pagebuilder's ``test_scheduler_claim_edges.py`` (#127): the claim is
the same conditional ``UPDATE`` in both modules, and news had the staged races
without either of these.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from factories import make_article
from news.content import ArticlesService
from news.content._claims import claim, due_candidates
from news.models import ArticleStatus, NewsArticle, NewsArticleRevision, RevisionEvent
from pg_support import USING_POSTGRES, make_db_state
from simple_module_db import tenant_context
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=1)
PUBLISH_CLAIM = {"column": NewsArticle.publish_at, "status": ArticleStatus.DRAFT}


async def _due_draft(db, slug: str) -> int:
    article = await make_article(db, slug=slug, status=ArticleStatus.DRAFT, publish_body=False)
    await ArticlesService(db).schedule(article.id, publish_at=EARLIER)
    await db.commit()
    return article.id


@pytest.mark.unbound_tenant
async def test_a_claim_cannot_reach_another_tenants_article() -> None:
    """The claim is an ORM ``UPDATE`` on a tenant-filtered table (#38): a tick
    bound to one tenant must not clear another tenant's schedule."""
    state = await make_db_state()
    state.tenant_strict = True
    try:
        with tenant_context("acme"):
            async with state.session_factory() as db:
                article_id = await _due_draft(db, "theirs")
        with tenant_context("globex"):
            async with state.session_factory() as db:
                assert await claim(db, article_id, now=NOW, **PUBLISH_CLAIM) is False
                assert await due_candidates(db, now=NOW, **PUBLISH_CLAIM) == []
                await db.commit()
        with tenant_context("acme"):
            async with state.session_factory() as db:
                assert (await db.get(NewsArticle, article_id)).publish_at is not None
    finally:
        await state.engine.dispose()


@pytest.mark.skipif(
    not USING_POSTGRES,
    reason="SQLite's StaticPool shares one connection, so two ticks are not two "
    "transactions; set SM_TEST_DATABASE_URL=postgresql+asyncpg://…",
)
async def test_two_concurrent_ticks_publish_once() -> None:
    """The half the staged tests cannot prove: the engine serialising the two
    claims. Each tick is its own session and connection, committing at the end,
    and the loser blocks on the winner's row lock then matches nothing."""
    state = await make_db_state()
    factory = state.session_factory
    try:
        async with factory() as db:
            article_id = await _due_draft(db, "stampede")

        async def tick() -> int:
            async with factory() as db:
                flipped = await ArticlesService(db).process_due(NOW)
                await db.commit()
                return len(flipped)

        assert sorted(await asyncio.gather(tick(), tick(), tick())) == [0, 0, 1]
        async with factory() as db:
            revisions = await db.execute(
                select(func.count())
                .select_from(NewsArticleRevision)
                .where(
                    NewsArticleRevision.article_id == article_id,
                    NewsArticleRevision.event == RevisionEvent.PUBLISH,
                )
            )
            assert revisions.scalar_one() == 1
    finally:
        await state.engine.dispose()
