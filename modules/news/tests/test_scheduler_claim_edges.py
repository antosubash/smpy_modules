"""The claim's two edges a single shared session cannot stage: which tenant a
claim can reach, and two genuinely concurrent ticks.

Ported from pagebuilder's ``test_scheduler_claim_edges.py`` (#127): the claim is
the same conditional ``UPDATE`` in both modules, and news had the staged races
without either of these.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from factories import make_article
from news.content import ArticlesService, _workflow
from news.content._claims import claim, due_candidates
from news.models import ArticleStatus, NewsArticle, NewsArticleRevision, RevisionEvent
from pg_support import make_db_state
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


async def test_two_concurrent_ticks_publish_once(tmp_path) -> None:
    """The half the staged tests cannot prove: the engine serialising the two
    claims. Each tick is its own session and connection, committing at the end,
    and the loser blocks on the winner's lock — the row lock on Postgres,
    SQLite's write lock on a file database (#209) — then matches nothing."""
    state = await make_db_state(file=tmp_path / "ticks.db")
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


async def test_ticks_that_all_shortlisted_the_row_publish_it_once(tmp_path, monkeypatch) -> None:
    """The claim itself, with every tick past the shortlist before any claims.

    On SQLite the test above never reaches the claim: each tick's first
    statement, ``retire_missed_windows``, is an ``UPDATE``, so it takes the
    database's write lock and the next tick waits for the whole first tick to
    commit, then shortlists nothing. Here the retire step is skipped (it has
    nothing to retire) and the ticks wait at a barrier once each has read its
    shortlist, so three ticks hold the same due row and the conditional
    ``UPDATE`` alone decides who flips it — on either backend.
    """
    state = await make_db_state(file=tmp_path / "claims.db")
    factory = state.session_factory
    barrier = asyncio.Barrier(3)

    async def nothing_to_retire(*_args, **_kwargs) -> int:
        return 0

    async def shortlist_then_wait(db, *, column, **kwargs):
        rows = await due_candidates(db, column=column, **kwargs)
        if column is NewsArticle.publish_at:
            await asyncio.wait_for(barrier.wait(), timeout=10)
        return rows

    monkeypatch.setattr(_workflow, "retire_missed_windows", nothing_to_retire)
    monkeypatch.setattr(_workflow, "due_candidates", shortlist_then_wait)
    try:
        async with factory() as db:
            await _due_draft(db, "shortlisted")

        async def tick() -> int:
            async with factory() as db:
                flipped = await ArticlesService(db).process_due(NOW)
                await db.commit()
                return len(flipped)

        assert sorted(await asyncio.gather(tick(), tick(), tick())) == [0, 0, 1]
    finally:
        await state.engine.dispose()
