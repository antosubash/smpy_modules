"""An article, and the ways one is created and changed."""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from news.constants import (
    MAX_CATEGORY_LEN,
    MAX_LOCALE_LEN,
    MAX_SLUG_LEN,
    MAX_TITLE_LEN,
    SLUG_PATTERN,
)
from news.display_date import as_display_date


class ArticleStatus(str, enum.Enum):  # noqa: UP042
    """Workflow state of the page behind an article.

    News' own enum, deliberately, even though the values are pagebuilder's
    ``PageStatus`` verbatim. A DTO is a contract with this module's callers,
    and re-exporting a neighbour's enum through it made every consumer — the
    OpenAPI schema, the generated TypeScript client — depend on pagebuilder's
    package layout to name a value news is perfectly able to name itself.

    The values match, so the wire format is unchanged and the mapping in
    ``integrations.pagebuilder.article_status`` is total by construction —
    ``test_integrations`` fails if pagebuilder ever adds a fourth state.
    """

    DRAFT = "draft"
    SUBMITTED_FOR_REVIEW = "submitted_for_review"
    PUBLISHED = "published"


class ArticleRead(BaseModel):
    """An article, flattened from its sidecar row plus the page it belongs to."""

    id: int
    page_id: int
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
    """Which language the article is written in.

    The page's, because an article *is* a page — there is no second copy of it
    on the sidecar row that could drift. Defaulted rather than required so a
    caller constructing an ``ArticleRead`` by hand (the search screen does)
    does not have to supply it.
    """

    translation_group: str = ""
    """What this article and its counterparts in other languages share.

    Carried on the card so the admin list can mark which articles already have
    a translation without a query per row.
    """

    page_status: ArticleStatus
    """Workflow state of the page behind the article.

    Lets the admin list mark a draft without a second request per row. Anyone
    without ``news.edit`` only ever sees ``PUBLISHED`` — drafts are filtered
    out of the listing before this field is set.
    """

    url: str
    """Where the article actually serves.

    An article *is* a page, so this is the page's own public URL rather than a
    route this module owns — duplicating the public viewer would mean
    duplicating its ETag, cache, CSP, SEO and site-layout handling.
    """

    edit_url: str
    """Where an author edits the body.

    Served rather than assembled in the browser so the admin list holds no
    opinion about how another module routes its editor.
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
    """Attach article metadata to an existing page."""

    page_id: int
    category: str = Field(default="", max_length=MAX_CATEGORY_LEN)
    published_at: datetime | None = None
    author: str = Field(default="", max_length=120)

    _display_date = field_validator("published_at")(as_display_date)
    """Truncate to the calendar day as sent — see ``news.display_date``."""


class ArticleWithPageCreate(BaseModel):
    """Create the page *and* attach the article to it, in one request.

    The two-call version of this ran in the browser and could only ever be
    half-done: if attaching failed after the page was created, an empty
    articleless page was left behind with nothing to clean it up — which is why
    the dialog had to remember the page a failed attempt had committed so a
    retry could adopt it.

    ``slug`` is optional. Omitted, the server derives a free one from the
    title; supplied, it is used verbatim and a collision is a 409, because a
    URL the author typed should not be silently changed under them.
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
    author: str = Field(default="", max_length=120)

    _display_date = field_validator("published_at")(as_display_date)
    """Truncate to the calendar day as sent — see ``news.display_date``."""


class ArticleTranslationCreate(BaseModel):
    """Start an article's counterpart in another language.

    Only the three things a translator decides. Category, byline, date, pin and
    feed membership are copied from the source rather than asked for again:
    they are facts about the story, not about the language it is told in, and
    a form that asked would invite them to drift apart between languages.
    """

    locale: str = Field(min_length=2, max_length=MAX_LOCALE_LEN)
    slug: str | None = Field(
        default=None, max_length=MAX_SLUG_LEN, pattern=SLUG_PATTERN
    )
    """Address within the new language. Defaults to the source article's own,
    which is free unless an unrelated page already took it — slugs are unique
    per language, so ``/news/x`` and ``/de/news/x`` do not collide."""

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LEN)
    """Defaults to the source's headline, i.e. untranslated — which is a more
    useful starting point for a translator than a blank field, and makes what
    still needs doing obvious in the list."""


class ArticleUpdate(BaseModel):
    category: str | None = Field(default=None, max_length=MAX_CATEGORY_LEN)
    published_at: datetime | None = None
    pinned: bool | None = None
    show_in_feed: bool | None = None
    author: str | None = Field(default=None, max_length=120)

    _display_date = field_validator("published_at")(as_display_date)
    """Truncate to the calendar day as sent — see ``news.display_date``."""


class ArticleTagsUpdate(BaseModel):
    """Full replacement set — a tag the writer removed has to disappear."""

    tags: list[str] = Field(default_factory=list)
