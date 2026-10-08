"""The article itself — body, workflow, SEO and listing metadata.

An article used to be a *sidecar*: a category and a date attached by id to a
``pagebuilder_pages`` row that held everything else. Every listing was a join,
the row carried no foreign key it could cascade from, and the module could not
be installed without its neighbour.

It owns its content now. The columns below that look like pagebuilder's are not
borrowed from it — they are what any document with a public URL needs, and
having them here is what lets ``simple_module_news`` be installed, migrated and
served on its own.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import uuid4

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import JSON, Column, DateTime, Index
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

from news import locales
from news.constants import (
    MAX_AUTHOR_LEN,
    MAX_CATEGORY_LEN,
    MAX_LOCALE_LEN,
    MAX_NOTE_LEN,
    MAX_SLUG_LEN,
    MAX_TITLE_LEN,
    MAX_TRANSLATION_GROUP_LEN,
    MAX_URL_LEN,
)
from news.models._base import ARTICLE_TABLE, Base


def _new_translation_group() -> str:
    return uuid4().hex


# Deliberately (str, Enum) rather than enum.StrEnum: these values are persisted
# and serialised, and StrEnum changes what str()/f-strings produce for a member
# ("draft" instead of "ArticleStatus.DRAFT"). Switching is a data-format change,
# not a style fix.
class ArticleStatus(str, enum.Enum):  # noqa: UP042
    """Workflow state of an article.

    The values are the ones the wire format has always carried, so a client
    written against the sidecar era still reads them. What changed is who owns
    them: this is news' own enum on news' own column, not a neighbour's status
    mapped across a module boundary.
    """

    DRAFT = "draft"
    SUBMITTED_FOR_REVIEW = "submitted_for_review"
    PUBLISHED = "published"


class NewsArticle(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    """An article: its body, its language, its address, and how it lists."""

    __tablename__ = ARTICLE_TABLE

    __table_args__ = (
        # Slugs are unique per tenant and language, not globally:
        # /news/budget and /de/news/budget are two articles at two addresses.
        Index(
            "ix_news_articles_tenant_locale_slug",
            "tenant_id",
            "locale",
            "slug",
            unique=True,
        ),
        # One article per language per group, per tenant. Without it a double
        # submit of "add German" yields two German siblings.
        Index(
            "ix_news_articles_tenant_group_locale",
            "tenant_id",
            "translation_group",
            "locale",
            unique=True,
        ),
    )
    # Neither column carries its own index: both composites lead with
    # ``tenant_id`` and cover the lookups. Same shape as ``pagebuilder_pages``.

    id: int | None = Field(default=None, primary_key=True)

    # ── Address and headline ──────────────────────────────────────────
    slug: str = Field(max_length=MAX_SLUG_LEN)
    """The article's address within its language.

    Unique per tenant and ``locale``, not globally — see ``__table_args__``. When the slug
    changes a :class:`NewsArticleRedirect` is written, because the old URL is
    already in bookmarks and in a search index that has not recrawled; that
    redirect is scoped to this article's locale for the same reason the index
    is.
    """

    locale: str = Field(default_factory=locales.default, max_length=MAX_LOCALE_LEN)
    """Which language this article is written in.

    Its own column rather than the language of the pagebuilder page the body
    used to live in. That page is gone — the article carries its body now — so
    borrowing a neighbour's answer would mean news could not be multilingual,
    or even installed, without it.

    Every article has one, including on a monolingual site: a nullable column
    would mean every query had to spell "this locale or nothing", and the row
    that predates the feature would be the one that behaves differently.
    Existing rows are backfilled to the default locale, which is also the one
    that keeps serving at the unprefixed URL.

    Fixed for the article's lifetime. Moving one between languages would strand
    its slug in the old locale and orphan the redirect pointing at it, so there
    is no "change language" — there is
    ``POST /articles/{id}/translations``, which creates a sibling.
    """

    translation_group: str = Field(
        default_factory=_new_translation_group,
        max_length=MAX_TRANSLATION_GROUP_LEN,
    )
    """What an article and its translations share.

    A generated key rather than a foreign key to the "original", because there
    isn't one: translations are siblings, and pointing each at a source would
    make deleting the English article orphan the German and French ones — or,
    worse, quietly re-parent them. Every article gets its own group at creation
    and joins another's only by being created as a translation of it.
    """

    title: str = Field(max_length=MAX_TITLE_LEN)

    # ── Body ──────────────────────────────────────────────────────────
    draft_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    """What the editor saves, block by block. Never served publicly."""

    published_data: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    """The immutable snapshot served at the public URL until the next publish.

    Separate from ``draft_data`` so an author can keep working on a published
    article without every keystroke reaching its readers.
    """

    status: ArticleStatus = Field(
        default=ArticleStatus.DRAFT,
        sa_column=Column(
            SAEnum(ArticleStatus, name="news_article_status"),
            nullable=False,
            index=True,
        ),
    )

    # ── SEO ───────────────────────────────────────────────────────────
    meta_description: str | None = Field(default=None, max_length=MAX_URL_LEN)
    """Also the card excerpt. One field because they are the same sentence, and
    two would drift the moment either was edited alone."""

    og_image: str | None = Field(default=None, max_length=MAX_URL_LEN)
    """Also the card's cover image, for the same reason as
    ``meta_description``."""

    canonical_url: str | None = Field(default=None, max_length=MAX_URL_LEN)
    """Override the canonical URL. Defaults to the article's own absolute
    address, which is right far more often than not."""

    index_in_search: bool = Field(default=True)
    """When ``False``, emit ``<meta name="robots" content="noindex,nofollow">``
    and keep the article out of the sitemap."""

    json_ld: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    """Optional schema.org document rendered in a ``<script
    type="application/ld+json">`` tag."""

    rejection_note: str | None = Field(default=None, max_length=MAX_NOTE_LEN)
    """Latest reviewer's reason for sending a submission back to draft.

    Cleared on every submit / approve / publish so a stale note does not shadow
    a new round.
    """

    # ── Trash ─────────────────────────────────────────────────────────
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    """When the article was moved to trash. ``None`` means it is live.

    A soft delete, so a mistake is recoverable. Every listing filters on this —
    see ``NOT_TRASHED`` — and the public viewer does too, so a trashed article
    404s the moment it is binned rather than lingering until it is purged.

    The slug stays claimed while an article is in the trash: releasing it would
    let a new article take the URL, and restoring the old one would then either
    collide or silently steal the address back.
    """

    # ── Listing metadata ──────────────────────────────────────────────
    category: str = Field(default="", max_length=MAX_CATEGORY_LEN, index=True)
    """Free-text grouping. Empty means uncategorised, which still lists."""

    pinned: bool = Field(default=False, index=True)
    """Hold this article at the top of the archive and of every feed block.

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

    author: str = Field(default="", max_length=MAX_AUTHOR_LEN)
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

    Deliberately distinct from ``status``: an article can be published without a
    display date (it is then work in progress in the archive's eyes and sorts
    into the undated pile), and can carry a date while still a draft.
    """

    @property
    def has_published(self) -> bool:
        return self.published_data is not None

    publish_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    """When a draft should go live by itself, or ``None`` for never.

    Deliberately *not* ``published_at``. That is the article's display date and
    is documented as independent of status — an article may carry a date while
    still a draft, and back-dating one is ordinary editorial work. Publishing on
    it would turn every back-dated draft live the moment the scheduler next
    woke, which is the opposite of what the author meant.

    So this is a separate instant with one job: an intention to publish, cleared
    the moment it is acted on. The pattern, the column names and the settings
    that drive it match ``pagebuilder``'s, because a host running both should
    not have to learn two vocabularies for one idea.
    """

    unpublish_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    """When a published article should come down by itself. Embargoes expire,
    and an offer or a notice that has stopped being true is worse than one that
    was never posted."""


NOT_TRASHED = NewsArticle.deleted_at.is_(None)
"""Every listing's filter. Named once so a new query cannot quietly omit it.

A trashed article is invisible everywhere except the trash screen itself, which
asks for the complement.
"""
