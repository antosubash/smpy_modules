"""Old slugs that still have to resolve."""

from __future__ import annotations

from sqlmodel import Field

from news.constants import MAX_SLUG_LEN
from news.models._base import ARTICLE_TABLE, Base


class NewsArticleRedirect(Base, table=True):  # ty: ignore[unsupported-base]
    """An old slug that should now send readers to an article's current one.

    Written whenever a slug changes, because the old URL is already out in the
    world — in someone's bookmarks, in a link from another site, in a search
    index that has not recrawled. Losing it silently turns an edit into a broken
    link that nobody notices until traffic drops.

    ``from_slug`` is unique: one old address resolves to exactly one article,
    and the row is replaced rather than duplicated when a slug is reused.
    """

    __tablename__ = "news_article_redirects"

    id: int | None = Field(default=None, primary_key=True)
    from_slug: str = Field(max_length=MAX_SLUG_LEN, unique=True, index=True)
    article_id: int = Field(
        foreign_key=f"{ARTICLE_TABLE}.id", index=True, ondelete="CASCADE"
    )
