"""Wildcards in a query are matched literally — in both directions.

The existing `test_wildcards_are_escaped` only asserts that searching for a
bare ``%`` does not match everything. That passes for the wrong reason when the
pattern is escaped but the ``ESCAPE`` clause is missing: SQLite then treats the
backslash as an ordinary character, so the pattern demands a literal backslash
no real content has, and the search silently returns nothing at all.

So there are two halves to assert, and only together do they pin the behaviour:

* a query containing ``%`` or ``_`` must still FIND content that contains it
* a query containing ``_`` must NOT match content differing at that position
"""

from __future__ import annotations

import pytest
from conftest import make_page
from news import search_service
from news.models import NewsArticle
from pagebuilder.models import PageStatus
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _article(db: AsyncSession, slug: str, title: str) -> NewsArticle:
    page = await make_page(db, slug=slug, title=title, status=PageStatus.PUBLISHED)
    article = NewsArticle(page_id=page.id, category="Research")
    db.add(article)
    await db.commit()
    await db.refresh(article)
    return article


async def test_a_percent_in_the_query_still_finds_it(db) -> None:
    """The half the old test could not see: escaping must not break matching."""
    await _article(db, "growth", title="Canopy cover rose 4% this spring")

    results = await search_service.search(db, "rose 4%")

    assert [h.title for h in results.articles] == ["Canopy cover rose 4% this spring"]


async def test_an_underscore_in_the_query_still_finds_it(db) -> None:
    await _article(db, "asset-note", title="Replacing hero_1 across the site")

    results = await search_service.search(db, "hero_1")

    assert [h.title for h in results.articles] == ["Replacing hero_1 across the site"]


async def test_an_underscore_does_not_act_as_a_wildcard(db) -> None:
    """`_` matches any single character in LIKE unless it is escaped."""
    await _article(db, "different", title="Replacing heroX1 across the site")

    results = await search_service.search(db, "hero_1")

    assert results.total == 0


async def test_a_bare_percent_still_matches_nothing(db) -> None:
    """The original guarantee, kept."""
    await _article(db, "plain", title="Plain article")

    results = await search_service.search(db, "%")

    assert results.total == 0
