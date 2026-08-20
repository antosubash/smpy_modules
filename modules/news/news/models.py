"""SQLModel table for the news module.

An article *is* a pagebuilder page — title, slug, body, approval workflow,
revisions and SEO all live there, and it serves at ``/p/{slug}`` with the
existing ETag, cache and CSP handling. This table adds only what a page has no
concept of: the category it belongs to and the date it should be listed under.

Keeping it a sidecar is what lets pagebuilder stay a generic CMS that knows
nothing about news. The cost is that every listing is a join, and that
``page_id`` carries no database foreign key — see the field for why.
"""

from __future__ import annotations

from datetime import datetime

from simple_module_db.base import create_module_base
from simple_module_db.mixins import AuditMixin
from sqlalchemy import Column, DateTime, Integer
from sqlmodel import Field

from news.constants import MAX_CATEGORY_LEN, MAX_TAG_LEN

Base = create_module_base("news")

PAGE_TABLE = "pagebuilder_pages"


class NewsArticle(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """Article metadata attached to a pagebuilder page."""

    __tablename__ = "news_articles"

    id: int | None = Field(default=None, primary_key=True)

    page_id: int = Field(
        sa_column=Column(Integer, nullable=False, unique=True, index=True)
    )
    """The pagebuilder page holding the body, slug and workflow.

    Deliberately *not* a database foreign key. ``create_module_base`` gives
    every module its own ``MetaData``, so a cross-module ``ForeignKey`` cannot
    resolve its target table and SQLAlchemy raises ``NoReferencedTableError``
    when the mapper configures. The framework offers no cross-module FK and
    pagebuilder publishes no page-deleted event, so there is nothing to hang a
    cascade on either.

    Two things make that safe. Every listing inner-joins the page, so an article
    whose page was deleted stops appearing immediately rather than surfacing a
    broken link. And an orphan is removed rather than left invisible — by the
    ``PageDeleted`` subscription first, and by the startup sweep
    (``service.reconcile_orphans``) when that event is missed.

    The sweep is not belt-and-braces. An invisible orphan does not stay
    invisible: SQLite reuses a deleted row's id, so the row re-attaches to
    whatever page is created next and lists one article's category and date
    against another article's page.
    """

    category: str = Field(default="", max_length=80, index=True)
    """Free-text grouping. Empty means uncategorised, which still lists."""

    pinned: bool = Field(default=False, index=True)
    """Hold this article at the top of /news and of every feed block.

    Sorted on before the date rather than by faking one, so pinning does not
    rewrite when the article says it was published — un-pin it and the archive
    reads correctly again.
    """

    show_in_feed: bool = Field(default=True, index=True)
    """Whether feed blocks may list this article.

    An article can be published, reachable at its own URL and linked from
    elsewhere, without belonging in the chronological feed — a standing "about
    this project" piece, say. Deliberately does not affect the admin list, which
    has to show everything that exists.
    """

    author: str = Field(default="", max_length=120)
    """Byline. Free text, not a user reference.

    A byline outlives the account: contributors leave, and an article credited
    to a deleted user row would either break or silently lose its author. It is
    seeded from whoever created the article and editable afterwards.
    """

    published_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    """The article's display date.

    Deliberately not ``Page.publish_at``, which is the single-shot scheduling
    field and is cleared on every flip — it would be empty for every article
    published immediately.
    """


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
    constraint. Both sides cascade — unlike ``NewsArticle.page_id``, these
    targets live in this module's own ``MetaData``, so a real foreign key
    resolves and the database can do the cleanup itself.
    """

    __tablename__ = "news_article_tags"

    article_id: int = Field(
        foreign_key="news_articles.id", primary_key=True, ondelete="CASCADE"
    )
    tag_id: int = Field(
        foreign_key="news_tags.id", primary_key=True, ondelete="CASCADE"
    )
