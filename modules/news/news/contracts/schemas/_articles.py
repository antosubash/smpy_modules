"""An article, and the ways one is created and changed.

Plural, matching pagebuilder's own ``_pages.py``: the file holds the listing
shape, the editor's, and every write, not one DTO.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from news.constants import (
    MAX_AUTHOR_LEN,
    MAX_CATEGORY_LEN,
    MAX_LOCALE_LEN,
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
    locale: str | None = Field(default=None, max_length=MAX_LOCALE_LEN)
    """Language to write in. ``None`` means the site's default.

    An article created this way starts a translation group of its own. Joining
    an existing one is ``POST /articles/{id}/translations``.
    """

    category: str = Field(default="", max_length=MAX_CATEGORY_LEN)
    published_at: datetime | None = None
    author: str = Field(default="", max_length=MAX_AUTHOR_LEN)

    _display_date = field_validator("published_at")(as_display_date)
    """Truncate to the calendar day as sent — see ``news.display_date``."""


class ArticleTranslationCreate(BaseModel):
    """Start an article's counterpart in another language.

    A translation is a *sibling article* sharing a ``translation_group``, not a
    second body on one row — and not, as it was while the body lived on a
    pagebuilder page, a translation of that page performed on the article's
    behalf.

    Only the three things a translator decides. Category, byline, date, pin and
    feed membership are copied from the source rather than asked for again:
    they are facts about the story, not about the language it is told in, and a
    form that asked would invite them to drift apart between languages.
    """

    locale: str = Field(min_length=2, max_length=MAX_LOCALE_LEN)
    slug: str | None = Field(
        default=None, max_length=MAX_SLUG_LEN, pattern=SLUG_PATTERN
    )
    """Address within the new language. Defaults to the source article's own,
    which is free unless an unrelated article already took it — slugs are
    unique per language, so ``/news/x`` and ``/de/news/x`` do not collide."""

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LEN)
    """Defaults to the source's headline, i.e. untranslated — a more useful
    starting point for a translator than a blank field, and it makes what still
    needs doing obvious in the list."""


class ArticleUpdate(BaseModel):
    """The listing metadata, and the article's identity and SEO.

    Every field is optional and only the ones actually sent are applied, so the
    admin list's inline edit can send two fields without clearing the rest.
    Changing ``slug`` records a redirect from the old one, scoped to the
    article's language.

    Deliberately no ``locale``: an article's language is fixed for its
    lifetime. Moving one would strand its slug in the old language and orphan
    the redirect pointing at it — ``POST /articles/{id}/translations`` starts a
    sibling instead.
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

    @model_validator(mode="after")
    def _no_null_for_required(self) -> ArticleUpdate:
        """Refuse ``null`` for a NOT NULL column; omitting it is fine.

        Otherwise the database rejects it and ``ArticlesService.update`` reports
        "Slug already in use" — a 409 about the wrong thing.
        """
        for name in ("title", "slug", "index_in_search"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ArticleBodyUpdate(BaseModel):
    """An autosave from the block canvas.

    Its own DTO, and its own endpoint, because it fires on a timer rather than
    on a person pressing something — so it must not be able to reach the slug,
    the status, or anything else a rename would record a redirect for.
    """

    draft_data: dict[str, Any] = Field(default_factory=dict)


class RejectRequest(BaseModel):
    note: str | None = Field(default=None, max_length=MAX_NOTE_LEN)


class ScheduleRequest(BaseModel):
    """When an article should go live, and when it should come down.

    Both fields are three-valued and the endpoint passes only what was actually
    sent: omitted leaves the column alone, an instant sets it, and an explicit
    ``null`` clears it. Cancelling a schedule has to be expressible, and is not
    the same as declining to mention one.

    Neither is truncated to a calendar day, unlike ``published_at``. That is a
    display date and the day is the whole of it; these are instants, and an
    embargo that lifts "some time on Tuesday" is not an embargo.
    """

    publish_at: datetime | None = None
    unpublish_at: datetime | None = None

    @field_validator("publish_at", "unpublish_at")
    @classmethod
    def _as_utc(cls, value: datetime | None) -> datetime | None:
        """Normalise to UTC: SQLite drops the offset on write without
        converting, and ``process_due`` reads stored values back as UTC."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class RevisionRead(BaseModel):
    """One row of the history panel."""

    id: int
    article_id: int
    title: str
    event: RevisionEvent
    note: str | None = None
    created_at: datetime | None = None
    created_by: str | None = None


