"""News articles for the card tests, written straight to news' table (a
test-only import: module code reads news only through ``news.contracts``)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from news.models import ArticleStatus, NewsArticle
from sm_newsletter.core.tenancy import tenant_scope
from sqlalchemy import update


async def seed_article(
    db_state: Any,
    tenant: str,
    *,
    slug: str = "spring-update",
    title: str = "Spring update",
    excerpt: str = "Hello",
    og_image: str | None = None,
) -> int:
    """A published article in ``tenant``; its id."""
    body = {"root": {"props": {"title": title}}, "content": []}
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            article = NewsArticle(
                slug=slug,
                title=title,
                status=ArticleStatus.PUBLISHED,
                draft_data=body,
                published_data=body,
                meta_description=excerpt,
                og_image=og_image,
                published_at=datetime(2026, 4, 1, tzinfo=UTC),
            )
            db.add(article)
            await db.commit()
            return article.id


async def change_article(db_state: Any, tenant: str, article_id: int, **values: Any) -> None:
    """Write ``values`` onto the article (``title``, ``status``, ``deleted_at``...)."""
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            stmt = (
                update(NewsArticle)
                .where(NewsArticle.id == article_id, NewsArticle.tenant_id == tenant)
                .values(**values)
                .execution_options(include_deleted=True)
            )
            await db.execute(stmt)
            await db.commit()


UNPUBLISHED = ArticleStatus.DRAFT
