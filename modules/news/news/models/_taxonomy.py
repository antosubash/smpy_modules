"""Categories and tags — the two ways an archive is grouped."""

from __future__ import annotations

from simple_module_db.mixins import AuditMixin
from sqlmodel import Field

from news.constants import MAX_CATEGORY_LEN, MAX_TAG_LEN
from news.models._base import ARTICLE_TABLE, Base


class NewsCategory(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """Display metadata for a category name that articles already carry.

    Deliberately *not* a foreign key from ``NewsArticle``. ``category`` is a
    published field on ``ArticleRead``/``ArticleCreate`` and the value the
    public feed block filters by; turning it into an id would break every
    consumer for the sake of normalisation this module does not need.

    So the article keeps the name and this table gives that name an ordering
    and a URL slug. Renaming is therefore a bulk update of the articles that
    carry the old name — see ``category_service.rename`` — which is exactly the
    semantics the categories screen offers.

    A category an author typed on an article but never formalised here has no
    row at all. Listings union the two sources so such a category still shows
    and can still be filtered on; it simply sorts after the ordered ones.
    """

    __tablename__ = "news_categories"

    id: int | None = Field(default=None, primary_key=True)

    name: str = Field(max_length=MAX_CATEGORY_LEN, index=True, unique=True)
    """Display name, and the value stored in ``NewsArticle.category``."""

    slug: str = Field(max_length=MAX_CATEGORY_LEN, index=True, unique=True)
    """URL segment for ``/news?category=<slug>``.

    Kept distinct from the name so renaming a category for display does not
    silently break links that already point at it.
    """

    position: int = Field(default=0, index=True)
    """Order in the public filter bar. Drag-to-reorder writes this."""


class NewsTag(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """A freeform label. Many per article, created while writing."""

    __tablename__ = "news_tags"

    id: int | None = Field(default=None, primary_key=True)

    name: str = Field(max_length=MAX_TAG_LEN, index=True, unique=True)
    slug: str = Field(max_length=MAX_TAG_LEN, index=True, unique=True)


class NewsArticleTag(Base, table=True):  # ty: ignore[unsupported-base]
    """Join row between an article and a tag.

    A composite primary key rather than a surrogate id: the pair *is* the
    identity, and it makes double-tagging impossible without a second unique
    constraint. Both sides cascade — these targets live in this module's own
    ``MetaData``, so a real foreign key resolves and the database can do the
    cleanup itself.
    """

    __tablename__ = "news_article_tags"

    article_id: int = Field(
        foreign_key=f"{ARTICLE_TABLE}.id", primary_key=True, ondelete="CASCADE"
    )
    tag_id: int = Field(
        foreign_key="news_tags.id", primary_key=True, ondelete="CASCADE"
    )
