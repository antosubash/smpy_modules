"""The scheduler tick runs once per tenant, each in its own tenant context."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from news import scheduler
from news.content import ArticlesService
from news.models import ArticleStatus, NewsArticle, NewsArticleRevision
from pg_support import make_db_state
from simple_module_db import current_tenant_id, tenant_context
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]


async def _env():
    state = await make_db_state()
    state.tenant_strict = True
    factory = async_sessionmaker(
        state.engine, expire_on_commit=False, sync_session_class=state.sync_session_class
    )
    return state, factory


async def _seed(factory, tenant: str, slug: str) -> int:
    with tenant_context(tenant):
        async with factory() as session:
            article = NewsArticle(
                title=slug,
                slug=slug,
                status=ArticleStatus.DRAFT,
                publish_at=datetime.now(UTC) - timedelta(minutes=1),
            )
            session.add(article)
            await session.commit()
            return article.id


async def test_due_work_runs_in_every_tenant() -> None:
    state, factory = await _env()
    try:
        a = await _seed(factory, "a", "x")
        b = await _seed(factory, "b", "y")
        await scheduler.Scheduler().tick(factory)
        for tenant, aid in (("a", a), ("b", b)):
            with tenant_context(tenant):
                async with factory() as session:
                    article = await session.get(NewsArticle, aid)
                    assert article.status == ArticleStatus.PUBLISHED
                    assert article.tenant_id == tenant
                    revs = (await session.execute(select(NewsArticleRevision))).scalars().all()
                    assert revs and {r.tenant_id for r in revs} == {tenant}
    finally:
        await state.engine.dispose()


async def test_one_tenant_failing_does_not_stop_others(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    state, factory = await _env()
    try:
        a = await _seed(factory, "a", "x")
        b = await _seed(factory, "b", "y")
        real = ArticlesService.process_due

        async def flaky(self, now):
            if current_tenant_id.get() == "a":
                raise RuntimeError("boom")
            return await real(self, now)

        monkeypatch.setattr(ArticlesService, "process_due", flaky)
        with caplog.at_level(logging.ERROR, logger=scheduler.logger.name):
            await scheduler.Scheduler().tick(factory)
        assert any(getattr(r, "tenant_id", None) == "a" for r in caplog.records)
        with tenant_context("a"):
            async with factory() as session:
                assert (await session.get(NewsArticle, a)).status == ArticleStatus.DRAFT
        with tenant_context("b"):
            async with factory() as session:
                assert (await session.get(NewsArticle, b)).status == ArticleStatus.PUBLISHED
    finally:
        await state.engine.dispose()
