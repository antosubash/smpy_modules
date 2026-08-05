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

    published_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    """The article's display date.

    Deliberately not ``Page.publish_at``, which is the single-shot scheduling
    field and is cleared on every flip — it would be empty for every article
    published immediately.
    """
