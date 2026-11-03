"""Published article cards for another module (the newsletter's article picker).

The caller names the tenant and it is pinned *here*, twice: bound with
:func:`news.core.tenancy.tenant_scope` (re-entering the bound tenant is a
no-op; naming a different one raises ``TenantIsolationError``) and added as a
``WHERE`` on ``NewsArticle.tenant_id``, because on a host with nothing bound
the framework's filter does nothing and an unpinned read lists every tenant.
An invalid ``tenant_id`` raises ``ValueError`` before any SQL runs. A strict
session with nothing bound (``MissingTenantError``) answers "nothing found".

Only *published, not trashed* articles are ever found or carded: a draft never
reaches a newsletter. ``path`` is site-relative and locale-prefixed except for the
default language, and ``image_url`` may be site-relative too; the caller makes
both absolute (prefixing the public base URL) before they go into an email.

``pattern`` is a SQL ``LIKE`` pattern with ``\\`` as the escape character; the
caller owns escaping, as in ``pagebuilder.contracts.search``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from simple_module_db import MissingTenantError
from sqlalchemy.ext.asyncio import AsyncSession

from news.content import card
from news.core.tenancy import tenant_scope
from news.models import NewsArticle

__all__ = ["MAX_ARTICLE_SEARCH_LIMIT", "ArticleCard", "get_article_card", "search_articles"]

MAX_ARTICLE_SEARCH_LIMIT = 50
"""The most cards one search returns."""


def _checked_limit(limit: object) -> int:
    # `bool` is an `int`; `True` as a limit is a caller bug, not "one row".
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError(f"limit must be an int, got {type(limit).__name__}")
    if not 1 <= limit <= MAX_ARTICLE_SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_ARTICLE_SEARCH_LIMIT}, got {limit}")
    return limit


class ArticleCard(BaseModel):
    """What a newsletter snapshots of a published article."""

    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    excerpt: str
    image_url: str
    """The cover image, or ``""`` when there is none. May be site-relative; the
    caller makes it absolute for email."""
    path: str
    """Site-relative, locale-prefixed except for the default language; the caller
    prefixes ``public_base_url``."""
    locale: str
    published_at: datetime | None


def _card_of(row: object) -> ArticleCard:
    read = card.to_read(row)
    return ArticleCard(
        id=read.id,
        title=read.title,
        excerpt=read.excerpt,
        image_url=read.cover_image_url,
        path=read.url,
        locale=read.locale,
        published_at=read.published_at,
    )


async def search_articles(
    session: AsyncSession,
    *,
    tenant_id: str,
    pattern: str,
    limit: int = 20,
    locale: str | None = None,
) -> list[ArticleCard]:
    """Published articles in ``tenant_id`` whose title matches ``pattern``.

    Newest ``published_at`` first, undated last. Every language unless ``locale`` names one.
    ``limit`` must be 1..:data:`MAX_ARTICLE_SEARCH_LIMIT`.
    """
    limit = _checked_limit(limit)
    with tenant_scope(tenant_id):
        stmt = card.base(include_drafts=False, category=None).where(
            NewsArticle.tenant_id == tenant_id,
            NewsArticle.title.ilike(pattern, escape="\\"),
        )
        if locale:
            stmt = stmt.where(NewsArticle.locale == locale)
        stmt = stmt.order_by(
            NewsArticle.published_at.desc().nullslast(), NewsArticle.id.desc()
        ).limit(limit)
        try:
            rows = (await session.execute(stmt)).all()
        except MissingTenantError:
            return []
    return [_card_of(r) for r in rows]


async def get_article_card(
    session: AsyncSession, *, tenant_id: str, article_id: int
) -> ArticleCard | None:
    """The card for one article, or ``None`` for an unknown, draft, trashed or
    other-tenant id."""
    with tenant_scope(tenant_id):
        stmt = card.base(include_drafts=False, category=None).where(
            NewsArticle.tenant_id == tenant_id, NewsArticle.id == article_id
        )
        try:
            row = (await session.execute(stmt)).first()
        except MissingTenantError:
            return None
    return _card_of(row) if row is not None else None
