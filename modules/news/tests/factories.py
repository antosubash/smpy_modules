"""Row builders the tests share.

Lifted out of ``conftest`` for two reasons. It had grown past the repo's
300-line cap, and — more usefully — ``from conftest import make_article`` is a
fragile way to share anything: ``conftest`` is a *top-level* module name, so in
a run that collects more than one module's tests it resolves to whichever
package's file reached ``sys.path`` first. That is why ``uv run pytest`` from the
repo root cannot collect this suite. Importing from a distinctly named module
removes news' share of that problem.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from news.models import ArticleStatus, NewsArticle
from sqlalchemy.ext.asyncio import AsyncSession


async def make_article(
    db: AsyncSession,
    *,
    slug: str,
    title: str = "An article",
    status: ArticleStatus = ArticleStatus.PUBLISHED,
    locale: str | None = None,
    translation_group: str | None = None,
    meta_description: str | None = None,
    og_image: str | None = None,
    category: str = "",
    author: str = "",
    published_at: datetime | None = None,
    pinned: bool = False,
    show_in_feed: bool = True,
    draft_data: dict | None = None,
    publish_body: bool = True,
) -> NewsArticle:
    """Insert an article. Committed, so an API request on another session sees it.

    ``publish_body`` mirrors what publishing actually does — it snapshots the
    draft — because the public viewer serves ``published_data`` and a fixture
    that left it null would 404 on rows the test believes are live.

    ``locale`` and ``translation_group`` are omitted rather than passed as
    ``None`` when a test does not care: both columns are non-nullable with a
    ``default_factory`` behind them, and handing the constructor a ``None``
    would override the factory with a value the column forbids.
    """
    body = (
        draft_data
        if draft_data is not None
        else {"root": {"props": {"title": title}}, "content": []}
    )
    optional: dict = {}
    if locale is not None:
        optional["locale"] = locale
    if translation_group is not None:
        optional["translation_group"] = translation_group
    article = NewsArticle(
        **optional,
        slug=slug,
        title=title,
        status=status,
        draft_data=body,
        published_data=(
            body if publish_body and status is ArticleStatus.PUBLISHED else None
        ),
        meta_description=meta_description,
        og_image=og_image,
        category=category,
        author=author,
        published_at=published_at,
        pinned=pinned,
        show_in_feed=show_in_feed,
    )
    db.add(article)
    await db.commit()
    await db.refresh(article)
    return article


@pytest.fixture
def make_article_factory():
    return make_article
