"""SQLModel tables for the pagebuilder module.

The page document itself is stored as opaque JSON; only the slug,
title, status, SEO fields, and timestamps are queried. ``draft_data`` is
what the editor saves; ``published_data`` is the immutable snapshot
served at ``/p/{slug}`` until a new publish overwrites it. Each publish
also appends a row to ``PageRevision`` so the history is recoverable.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from simple_module_db.base import create_module_base
from simple_module_db.mixins import AuditMixin
from sqlalchemy import JSON, Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

Base = create_module_base("pagebuilder")


# Deliberately (str, Enum) rather than enum.StrEnum: these values are persisted
# and serialised, and StrEnum changes what str()/f-strings produce for a member
# ("draft" instead of "PageStatus.DRAFT"). Switching is a data-format change,
# not a style fix.
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
    parent_id: int | None = Field(
        default=None, foreign_key="pagebuilder_pages.id", index=True, ondelete="SET NULL"
    )
    """Optional parent, for breadcrumbs only.

    Deliberately does *not* affect the URL: a page's public address is its slug
    and nothing else, so re-parenting for navigation never breaks a link that
    already exists. ``SET NULL`` rather than cascade for the same reason —
    deleting a parent must not delete its children.
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


class Layout(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """Singleton — :meth:`LayoutService.get` creates the row on first read."""

    __tablename__ = "pagebuilder_layout"

    id: int | None = Field(default=None, primary_key=True)
    header_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    footer_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )


class LayoutRevision(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "pagebuilder_layout_revisions"

    id: int | None = Field(default=None, primary_key=True)
    layout_id: int = Field(foreign_key="pagebuilder_layout.id", index=True)
    header_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    footer_data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    note: str | None = Field(default=None, max_length=2000)


class MediaAsset(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """An uploaded media file stored on local disk.

    The bytes themselves live under :attr:`PagebuilderSettings.media_root`;
    this row holds the metadata + sanitized filename used to build the
    public URL.

    ``width`` / ``height`` are populated for raster images so the Image
    block can emit them on ``<img>`` and avoid layout shift; ``variants``
    lists server-generated thumbnails / webp transcodes keyed by a stable
    label (e.g. ``"w640"``, ``"webp"``) — each entry stores at minimum
    ``{filename, width, height, content_type}``.
    """

    __tablename__ = "pagebuilder_media"

    id: int | None = Field(default=None, primary_key=True)
    filename: str = Field(max_length=300, unique=True, index=True)
    original_filename: str = Field(max_length=300)
    content_type: str = Field(max_length=120)
    size_bytes: int = Field(default=0)
    width: int | None = Field(default=None)
    height: int | None = Field(default=None)
    folder: str | None = Field(default=None, max_length=300, index=True)
    variants: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
