"""Article DTOs — the listing shape, the editor's, and every write."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from news.constants import (
    MAX_AUTHOR_LEN,
    MAX_CATEGORY_LEN,
    MAX_NOTE_LEN,
    MAX_SLUG_LEN,
    MAX_TITLE_LEN,
    MAX_URL_LEN,
    SLUG_PATTERN,
)
from news.display_date import as_display_date
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
    status: ArticleStatus
    """Workflow state.

    Lets the admin list mark a draft without a second request per row. Anyone
    without ``news.edit`` only ever sees ``PUBLISHED`` — drafts are filtered
    out of the listing before this field is set.
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


class CategoryCount(BaseModel):
    category: str
    count: int


class CategoryListResponse(BaseModel):
    items: list[CategoryCount]


class ArticleCreate(BaseModel):
    """Create an article.

    This used to be two DTOs and two requests: one that created a *page* and one
    that attached news metadata to it, which could only ever be half-done — a
    failure of the second stranded an empty, articleless page with nothing to
    clean it up, and the dialog had to remember the first request's id so a
    retry could adopt it. One table means one insert.

    ``slug`` is optional. Omitted, the server derives a free one from the title;
    supplied, it is used verbatim and a collision is a 409, because a URL the
    author typed should not be silently changed under them.
    """

    title: str = Field(min_length=1, max_length=MAX_TITLE_LEN)
    slug: str | None = Field(
        default=None, max_length=MAX_SLUG_LEN, pattern=SLUG_PATTERN
    )
    category: str = Field(default="", max_length=MAX_CATEGORY_LEN)
    published_at: datetime | None = None
    author: str = Field(default="", max_length=MAX_AUTHOR_LEN)

    _display_date = field_validator("published_at")(as_display_date)
    """Truncate to the calendar day as sent — see ``news.display_date``."""


class ArticleUpdate(BaseModel):
    """The listing metadata, and the article's identity and SEO.

    Every field is optional and only the ones actually sent are applied, so the
    admin list's inline edit can send two fields without clearing the rest.
    Changing ``slug`` records a redirect from the old one.
    """

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LEN)
    slug: str | None = Field(
        default=None, max_length=MAX_SLUG_LEN, pattern=SLUG_PATTERN
    )
    category: str | None = Field(default=None, max_length=MAX_CATEGORY_LEN)
    published_at: datetime | None = None
    pinned: bool | None = None
    show_in_feed: bool | None = None
    author: str | None = Field(default=None, max_length=MAX_AUTHOR_LEN)
    meta_description: str | None = Field(default=None, max_length=MAX_URL_LEN)
    og_image: str | None = Field(default=None, max_length=MAX_URL_LEN)
    canonical_url: str | None = Field(default=None, max_length=MAX_URL_LEN)
    index_in_search: bool | None = None
    json_ld: dict[str, Any] | None = None

    _display_date = field_validator("published_at")(as_display_date)
    """Truncate to the calendar day as sent — see ``news.display_date``."""


class ArticleBodyUpdate(BaseModel):
    """An autosave from the block canvas.

    Its own DTO, and its own endpoint, because it fires on a timer rather than
    on a person pressing something — so it must not be able to reach the slug,
    the status, or anything else a rename would record a redirect for.
    """

    draft_data: dict[str, Any] = Field(default_factory=dict)


class RejectRequest(BaseModel):
    note: str | None = Field(default=None, max_length=MAX_NOTE_LEN)


class RevisionRead(BaseModel):
    """One row of the history panel."""

    id: int
    article_id: int
    title: str
    event: RevisionEvent
    note: str | None = None
    created_at: datetime | None = None
    created_by: str | None = None


