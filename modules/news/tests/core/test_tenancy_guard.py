"""The fail-closed guard — ``news.core.tenancy.install_guard`` (#335).

The same guard records, images and newsletter install: with it on the session
class, news ORM work with no tenant bound raises instead of reading every
tenant's rows. These pin that it covers every news table, that startup installs
it, and that the entry points that run with nothing bound — the scheduler's
tenant enumeration and the article contract newsletter calls — still work under
it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from news.contracts.articles import get_article_card, search_articles
from news.core.tenancy import (
    TenantIsolationError,
    TenantUnbound,
    all_tenants,
    install_guard,
    tenant_scope,
)
from news.core.tenancy._guard import is_guarded, owned
from news.models import ArticleStatus, Base, NewsArticle, NewsTag
from news.scheduling import scheduler
from pg_support import make_db_state
from sqlalchemy import func, select
from sqlmodel import SQLModel

from tests.support.app import _build_app

pytestmark = pytest.mark.unbound_tenant


@pytest.fixture
async def guarded():
    state = await make_db_state()
    install_guard(state.sync_session_class)
    install_guard(state.sync_session_class)  # idempotent
    try:
        yield state
    finally:
        await state.engine.dispose()


async def _seed(state, tenant: str, slug: str, **kw) -> int:
    with tenant_scope(tenant):
        async with state.session_factory() as session:
            article = NewsArticle(title=slug, slug=slug, **kw)
            session.add(article)
            await session.commit()
            return article.id


def test_every_news_table_is_guarded():
    """Every table in news' metadata belongs to a class the guard owns."""
    guarded = {
        mapper.local_table.name
        for mapper in SQLModel._sa_registry.mappers
        if owned(mapper.class_)
    }
    assert guarded and guarded == set(Base.metadata.tables)


async def test_an_unbound_read_or_write_is_refused(guarded):
    await _seed(guarded, "acme", "a")
    assert is_guarded(guarded.sync_session_class)
    async with guarded.session_factory() as session:
        with pytest.raises(TenantUnbound, match="NewsArticle"):
            await session.execute(select(NewsArticle))
        with pytest.raises(TenantUnbound):
            await session.execute(select(func.count(NewsTag.id)))
    async with guarded.session_factory() as session:
        session.add(NewsTag(name="x", slug="x", tenant_id="acme"))
        with pytest.raises(TenantUnbound, match="written with no tenant bound"):
            await session.flush()


async def test_a_tagged_read_passes_and_a_bound_one_is_still_filtered(guarded):
    await _seed(guarded, "acme", "a")
    await _seed(guarded, "globex", "b")
    async with guarded.session_factory() as session:
        stmt = all_tenants(select(NewsArticle.tenant_id).order_by(NewsArticle.tenant_id))
        assert (await session.execute(stmt)).scalars().all() == ["acme", "globex"]
    with tenant_scope("acme"):
        async with guarded.session_factory() as session:
            assert (await session.execute(select(NewsArticle.slug))).scalars().all() == ["a"]


async def test_the_scheduler_tick_runs_under_the_guard(guarded):
    past = datetime.now(UTC) - timedelta(minutes=1)
    ids = {
        t: await _seed(guarded, t, t, status=ArticleStatus.DRAFT, publish_at=past)
        for t in ("acme", "globex")
    }
    await scheduler.Scheduler().tick(guarded.session_factory)
    for tenant, article_id in ids.items():
        with tenant_scope(tenant):
            async with guarded.session_factory() as session:
                article = await session.get(NewsArticle, article_id)
                assert article is not None and article.status == ArticleStatus.PUBLISHED


async def test_the_article_contract_binds_the_tenant_it_is_given(guarded):
    """Unbound (a caller outside a request), it binds the named tenant; bound
    to another one, it refuses."""
    now = datetime.now(UTC)
    published = {"status": ArticleStatus.PUBLISHED, "published_at": now}
    acme = await _seed(guarded, "acme", "alpha", **published)
    await _seed(guarded, "globex", "alpine", **published)
    async with guarded.session_factory() as session:
        cards = await search_articles(session, tenant_id="acme", pattern="%alp%")
        assert [c.id for c in cards] == [acme]
        assert await get_article_card(session, tenant_id="globex", article_id=acme) is None
    with tenant_scope("acme"):
        async with guarded.session_factory() as session:
            with pytest.raises(TenantIsolationError):
                await search_articles(session, tenant_id="globex", pattern="%alp%")


async def test_startup_installs_the_guard():
    _app, state = await _build_app(None, mount_public=True)
    try:
        assert is_guarded(state.sync_session_class)
    finally:
        await state.engine.dispose()
