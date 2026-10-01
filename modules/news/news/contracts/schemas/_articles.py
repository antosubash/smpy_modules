"""An article as a screen reads it back — the listing shape, the editor's, and
the history row.

Plural, matching pagebuilder's own ``_pages.py``: the file holds several DTOs,
not one. The request bodies that write an article are in ``_writes.py``, which
is where this file's other half went when it reached the 300-line cap.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from news.models import ArticleStatus, RevisionEvent


class ArticleRead(BaseModel):
    """An article as the listing, the feed block and the archive see it.

    Everything here is a column on ``news_articles``. It used to be half a join
    onto a pagebuilder page, which is why the wire format once carried a
    ``page_id`` and called the workflow field ``page_status``: both named a row
    in another module's table. Neither exists now — there is one row, and it is
    this module's.
    """

    id: int
    slug: str
    title: str
    excerpt: str = ""
    cover_image_url: str = ""
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False
    show_in_feed: bool = True
    author: str = ""
    published_at: datetime | None = None

    locale: str = ""
    """Which language the article is written in. Defaulted so a caller building
    an ``ArticleRead`` by hand — the search screen does — need not supply it."""

    translation_group: str = ""
    """What this article and its counterparts in other languages share.

    Carried on the card so the admin list can mark which articles have a
    translation without a query per row. Empty only where the caller built the
    shape by hand; every stored article has one, a lone one being a group of one.
    """

    status: ArticleStatus
    """Workflow state.

    Lets the admin list mark a draft without a second request per row. Anyone
    without ``news.edit`` only ever sees ``PUBLISHED`` — drafts are filtered
    out of the listing before this field is set.
    """

    has_unpublished_changes: bool = False
    """Readers are being served an older document than this one.

    True only for an article that is genuinely live — published *and* holding a
    snapshot — whose draft has since diverged. Sent only to a caller who may
    see drafts: it is a statement about work in progress. See
    ``card.HAS_UNPUBLISHED_CHANGES``.
    """

    url: str
    """Where the article serves publicly — ``NewsSettings.public_route_prefix``
    plus its slug."""

    edit_url: str
    """Where the body is composed.

    Served rather than assembled in the browser so the admin list holds no
    opinion about how this module routes its own screens.
    """


class ArticleDetail(ArticleRead):
    """One article, with the fields only its editor needs.

    Extends the listing shape rather than replacing it so a screen holding an
    ``ArticleRead`` can be handed one of these without branching, and so the two
    can never disagree about what a title or a slug is.
    """

    draft_data: dict[str, Any] = Field(default_factory=dict)
    """The block document the canvas edits. Never what readers are served —
    that is the snapshot taken at publish."""

    has_published: bool = False
    """Whether a published snapshot exists. Distinct from ``status``: an
    unpublished article can still have one, from before it was taken down."""

    meta_description: str = ""
    og_image: str = ""
    canonical_url: str = ""
    index_in_search: bool = True
    json_ld: dict[str, Any] | None = None
    rejection_note: str | None = None

    publish_at: datetime | None = None
    unpublish_at: datetime | None = None
    """When the article goes live and comes down by itself.

    On the editor's shape rather than the listing's, and that is the point: a
    published article can carry a future ``unpublish_at``, and the listing DTO
    is what anonymous readers are served. There is no reason for a reader to
    learn when a piece is scheduled to be taken down.
    """


class ArticleCounts(BaseModel):
    """How many articles each status pill would show.

    Scoped by the current search and category but *not* by the active status —
    otherwise every pill but the selected one reads zero. ``undated`` cuts
    across draft and published rather than being a third status, so the four
    numbers deliberately do not sum to ``all``.
    """

    all: int = 0
    draft: int = 0
    published: int = 0
    undated: int = 0


class ArticleListResponse(BaseModel):
    items: list[ArticleRead]
    total: int
    """How many matched the *whole* filter, including status — what the pager
    counts against."""

    counts: ArticleCounts = Field(default_factory=ArticleCounts)


class RevisionRead(BaseModel):
    """One row of the history panel."""

    id: int
    article_id: int
    title: str
    event: RevisionEvent
    note: str | None = None
    created_at: datetime | None = None
    created_by: str | None = None


