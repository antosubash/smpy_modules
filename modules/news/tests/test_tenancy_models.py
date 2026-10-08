"""Every news table carries ``tenant_id``; uniques are per tenant."""

from __future__ import annotations

import pytest
from factories import make_article
from news.models import NewsArticle, NewsCategory, NewsTag
from simple_module_db import tenant_context
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]


async def test_same_slug_and_category_in_two_tenants(db_state):
    for tenant in ("a", "b"):
        with tenant_context(tenant):
            async with db_state.session_factory() as s:
                s.add(NewsCategory(name="Sport", slug="sport"))
                s.add(NewsTag(name="Live", slug="live"))
                await make_article(s, slug="hello", locale="en")
                await s.commit()
    with tenant_context("a"):
        async with db_state.session_factory() as s:
            rows = (await s.execute(select(NewsArticle))).scalars().all()
            assert [r.tenant_id for r in rows] == ["a"]


async def test_duplicate_slug_in_one_tenant_still_rejected(db_state):
    with tenant_context("a"):
        async with db_state.session_factory() as s:
            s.add(NewsCategory(name="Sport", slug="sport"))
            s.add(NewsCategory(name="Sport", slug="sport"))
            with pytest.raises(IntegrityError):
                await s.commit()


async def test_unformalised_category_still_lists(db_state):
    from news import service

    with tenant_context("a"):
        async with db_state.session_factory() as s:
            s.add(NewsCategory(name="Ordered", slug="ordered", position=1))
            await make_article(s, slug="x", category="Ordered")
            await make_article(s, slug="y", category="Loose")
            await s.commit()
            names = [c.category for c in await service.list_categories(s, include_drafts=True)]
    assert names == ["Ordered", "Loose"]
