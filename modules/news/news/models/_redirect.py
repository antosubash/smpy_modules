"""Old slugs that still have to resolve."""

from __future__ import annotations

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import Index
from sqlmodel import Field

from news import locales
from news.constants import MAX_LOCALE_LEN, MAX_SLUG_LEN
from news.models._base import ARTICLE_TABLE, Base


class NewsArticleRedirect(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    """An old slug that should now send readers to an article's current one.

    Written whenever a slug changes, because the old URL is already out in the
    world — in someone's bookmarks, in a link from another site, in a search
    index that has not recrawled. Losing it silently turns an edit into a broken
    link that nobody notices until traffic drops.

    ``(tenant_id, locale, from_slug)`` is unique: one old address resolves to exactly one
    article, and the row is replaced rather than duplicated when a slug is
    reused.
    """

    __tablename__ = "news_article_redirects"

    __table_args__ = (
        Index(
            "ix_news_article_redirects_tenant_locale_from_slug",
            "tenant_id",
            "locale",
            "from_slug",
            unique=True,
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    from_slug: str = Field(max_length=MAX_SLUG_LEN)
    locale: str = Field(default_factory=locales.default, max_length=MAX_LOCALE_LEN)
    """Which language's address this was.

    Carried on the redirect rather than read off the article it points at,
    because slugs are only unique per language: without it, renaming the German
    article to a slug the French one had already retired would collide on a
    unique index the two rows have no reason to share.
    """

    article_id: int = Field(
        foreign_key=f"{ARTICLE_TABLE}.id", index=True, ondelete="CASCADE"
    )
