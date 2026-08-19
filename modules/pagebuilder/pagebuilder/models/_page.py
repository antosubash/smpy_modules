"""Pages, their revisions, and the filter every listing applies."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from simple_module_db.mixins import AuditMixin
from sqlalchemy import JSON, Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

from pagebuilder.models._base import Base


class PageStatus(str, enum.Enum):  # noqa: UP042
    DRAFT = "draft"
    SUBMITTED_FOR_REVIEW = "submitted_for_review"
    PUBLISHED = "published"


class RevisionEvent(str, enum.Enum):  # noqa: UP042  — see PageStatus above
    """Status-transition kind recorded in :class:`PageRevision`.

    ``PUBLISH`` and ``APPROVE`` rows snapshot the bytes served at
    ``/p/{slug}`` (approve also publishes), so the editor's
    Restore-as-draft affordance treats them identically. ``SUBMIT`` /
    ``REJECT`` / ``UNPUBLISH`` are audit-only — their ``data`` is the
    current draft, kept for forensics.
    """

    PUBLISH = "publish"
    UNPUBLISH = "unpublish"
    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"


class Page(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """A page composed in the visual editor."""

    __tablename__ = "pagebuilder_pages"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(max_length=200, unique=True, index=True)
    title: str = Field(max_length=300)
    meta_description: str | None = Field(default=None, max_length=500)
    og_image: str | None = Field(default=None, max_length=500)
    status: PageStatus = Field(
        default=PageStatus.DRAFT,
        sa_column=Column(
            SAEnum(PageStatus, name="pagebuilder_page_status"),
            nullable=False,
            index=True,
        ),
    )
    draft_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    published_data: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    canonical_url: str | None = Field(default=None, max_length=500)
    """Override the canonical URL emitted on the public page.

    Defaults to the page's own absolute URL (built from
    ``PagebuilderSettings.public_base_url`` + ``public_route_prefix`` +
    ``slug``) when unset, so the most common case requires no input.
    """
    meta_title: str | None = Field(default=None, max_length=200)
    """Title for search results and link previews.

    Separate from ``title`` because they answer different questions: the page
    title names the page inside the site, while this one has to work as a
    standalone line in a result list, usually with the site name appended. When
    unset the page title is used, which is right far more often than not.
    """

    show_in_header_nav: bool = Field(default=False, index=True)
    show_in_footer: bool = Field(default=False, index=True)
    """Whether the site layout's nav lists this page.

    Only membership lives here. The *order* is the layout's, set in the layout
    editor — a page deciding where it sits in someone else's list is how nav
    ordering becomes unexplainable.
    """

    parent_id: int | None = Field(
        default=None, foreign_key="pagebuilder_pages.id", index=True, ondelete="SET NULL"
    )
    """Optional parent, for breadcrumbs only.

    Deliberately does *not* affect the URL: a page's public address is its slug
    and nothing else, so re-parenting for navigation never breaks a link that
    already exists. ``SET NULL`` rather than cascade for the same reason —
    deleting a parent must not delete its children.
    """

    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    """When the page was moved to trash. ``None`` means it is live.

    A soft delete rather than a row removal, so a mistake is recoverable for the
    retention window. Every listing filters on this — see ``NOT_TRASHED`` — and
    the public viewer does too, so a trashed page answers 404 the moment it is
    binned rather than lingering until it is purged.

    The slug stays claimed while a page is in the trash. That is deliberate:
    releasing it would let a new page take the URL, and restoring the old one
    would then either collide or silently steal the address back.
    """

    is_template: bool = Field(default=False, index=True)
    """Offer this page as a starting point in the New page dialog.

    A template is an ordinary page carrying a flag rather than a separate kind
    of record, which is what lets the set of starting points grow without a
    developer. A template is never published; it is copied.
    """

    index_in_search: bool = Field(default=True)
    """When ``False``, emit ``<meta name="robots" content="noindex,nofollow">``
    on the public page and exclude it from the sitemap."""
    json_ld: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    """Optional schema.org JSON-LD document rendered inside a
    ``<script type="application/ld+json">`` tag on the public page."""
    rejection_note: str | None = Field(default=None, max_length=2000)
    """Latest approver-supplied reason for sending a submission back to draft.

    Cleared on every ``submit`` / ``approve`` / ``publish`` so a stale
    note doesn't shadow a new round.
    """
    publish_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    """When set, the scheduler flips a ``DRAFT`` page to ``PUBLISHED`` at
    or after this UTC instant. Cleared on every flip (auto or manual) so
    the schedule is single-shot."""
    unpublish_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    """When set, the scheduler flips a ``PUBLISHED`` page back to draft at
    or after this UTC instant. Independent of ``publish_at``; both can be
    set so a draft goes live on Monday and takes itself down on Friday."""

    @property
    def has_published(self) -> bool:
        return self.published_data is not None


class PageRevision(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """Append-only audit row written on every status transition.

    ``Page.rejection_note`` mirrors the most recent ``REJECT`` row's
    ``note`` so the editor banner avoids a join.
    """

    __tablename__ = "pagebuilder_page_revisions"

    id: int | None = Field(default=None, primary_key=True)
    page_id: int = Field(foreign_key="pagebuilder_pages.id", index=True)
    title: str = Field(max_length=300)
    meta_description: str | None = Field(default=None, max_length=500)
    og_image: str | None = Field(default=None, max_length=500)
    data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    event: RevisionEvent = Field(
        default=RevisionEvent.PUBLISH,
        sa_column=Column(
            SAEnum(RevisionEvent, name="pagebuilder_revision_event"),
            nullable=False,
            index=True,
            server_default=RevisionEvent.PUBLISH.value,
        ),
    )
    note: str | None = Field(default=None, max_length=2000)




NOT_TRASHED = Page.deleted_at.is_(None)
"""Every listing's filter. Named once so a new query cannot quietly omit it.

A trashed page is invisible everywhere except the trash screen itself, which
asks for the complement.
"""
