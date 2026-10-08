"""The audit trail: one row per status transition, and what it snapshotted.

Its own file rather than a second class in :mod:`news.models._article`, which
is at the repo's 300-line cap now that an article carries its own language.
The split is along the obvious seam — the article is the live document, this is
the history behind it.
"""

from __future__ import annotations

import enum
from typing import Any

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import JSON, Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

from news.constants import MAX_NOTE_LEN, MAX_TITLE_LEN, MAX_URL_LEN
from news.models._base import ARTICLE_TABLE, Base


# Deliberately (str, Enum) rather than enum.StrEnum: these values are persisted
# and serialised, and StrEnum changes what str()/f-strings produce for a member
# ("publish" instead of "RevisionEvent.PUBLISH"). Switching is a data-format
# change, not a style fix.
class RevisionEvent(str, enum.Enum):  # noqa: UP042
    """Status-transition kind recorded in :class:`NewsArticleRevision`.

    ``PUBLISH`` and ``APPROVE`` rows snapshot the bytes served at the article's
    public URL (approve also publishes), so restore-as-draft treats them
    identically. ``SUBMIT`` / ``REJECT`` / ``UNPUBLISH`` are audit-only — their
    ``data`` is the current draft, kept for forensics.
    """

    PUBLISH = "publish"
    UNPUBLISH = "unpublish"
    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"


class NewsArticleRevision(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    """Append-only audit row written on every status transition.

    ``NewsArticle.rejection_note`` mirrors the most recent ``REJECT`` row's
    ``note`` so the editor banner avoids a join.

    Deliberately carries no ``locale``: a revision belongs to one article, and
    an article's language is fixed for its lifetime — so the language is the
    article's to answer, and a copy here could only ever drift from it.
    """

    __tablename__ = "news_article_revisions"

    id: int | None = Field(default=None, primary_key=True)
    article_id: int = Field(
        foreign_key=f"{ARTICLE_TABLE}.id", index=True, ondelete="CASCADE"
    )
    title: str = Field(max_length=MAX_TITLE_LEN)
    meta_description: str | None = Field(default=None, max_length=MAX_URL_LEN)
    og_image: str | None = Field(default=None, max_length=MAX_URL_LEN)
    data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    event: RevisionEvent = Field(
        default=RevisionEvent.PUBLISH,
        sa_column=Column(
            SAEnum(RevisionEvent, name="news_revision_event"),
            nullable=False,
            index=True,
            # SAEnum stores the member *name* ("PUBLISH"), not its value
            # ("publish") — the default must match, or Postgres rejects the
            # DDL with "invalid input value for enum" at CREATE TABLE time.
            server_default=RevisionEvent.PUBLISH.name,
        ),
    )
    note: str | None = Field(default=None, max_length=MAX_NOTE_LEN)
