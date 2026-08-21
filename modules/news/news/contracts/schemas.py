"""DTOs for the News module — the public surface."""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from news.constants import (
    MAX_CATEGORY_LEN,
    MAX_SLUG_LEN,
    MAX_TAG_LEN,
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


class CategoryCount(BaseModel):
    category: str
    count: int


class CategoryListResponse(BaseModel):
    items: list[CategoryCount]


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
    category: str = Field(default="", max_length=MAX_CATEGORY_LEN)
    published_at: datetime | None = None
    author: str = Field(default="", max_length=120)

    _display_date = field_validator("published_at")(as_display_date)
    """Truncate to the calendar day as sent — see ``news.display_date``."""


class ArticleUpdate(BaseModel):
    category: str | None = Field(default=None, max_length=MAX_CATEGORY_LEN)
    published_at: datetime | None = None
    pinned: bool | None = None
    show_in_feed: bool | None = None
    author: str | None = Field(default=None, max_length=120)

    _display_date = field_validator("published_at")(as_display_date)
    """Truncate to the calendar day as sent — see ``news.display_date``."""


class CategoryRead(BaseModel):
    """A category row for the management screen.

    ``id`` is 0 for two different things the screen must tell apart from a real
    row: the system Uncategorised bucket (``is_system``), and a category that
    exists only as free text on articles with no table row yet. Neither can be
    renamed or reordered until it has one.
    """

    id: int
    name: str
    slug: str
    position: int
    article_count: int
    is_system: bool = False


class CategoryAdminListResponse(BaseModel):
    """The management screen's view.

    Distinct from ``CategoryListResponse``, which stays exactly as it was: that
    one backs the anonymous ``/api/news/categories`` the public feed block
    calls, and widening it would change a published contract for the sake of a
    screen only editors see.
    """

    items: list[CategoryRead]


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_CATEGORY_LEN)
    slug: str | None = Field(default=None, max_length=MAX_CATEGORY_LEN)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=MAX_CATEGORY_LEN)
    slug: str | None = Field(default=None, min_length=1, max_length=MAX_CATEGORY_LEN)


class CategoryReorder(BaseModel):
    """Full ordering, as dragged. Ids omitted keep the position they had."""

    ordered_ids: list[int]


class CategoryDeleteResult(BaseModel):
    reassigned: int
    """How many articles moved. Nothing is ever deleted with the category."""


class TagRead(BaseModel):
    id: int
    name: str
    slug: str
    article_count: int


class TagListResponse(BaseModel):
    items: list[TagRead]


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_TAG_LEN)


class TagUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_TAG_LEN)


class TagMerge(BaseModel):
    """Fold ``source_id`` into this tag; the source row is removed."""

    source_id: int


class TagMergeResult(BaseModel):
    moved: int


class ArticleTagsUpdate(BaseModel):
    """Full replacement set — a tag the writer removed has to disappear."""

    tags: list[str] = Field(default_factory=list)


class SearchHit(BaseModel):
    """One result, in whatever section found it."""

    id: int
    title: str
    subtitle: str
    """The line under the title — category and status, or a path, or a MIME
    type. Which of those it is depends on the section, which is why it is one
    pre-rendered string rather than a shape the screen has to branch on."""

    url: str
    excerpt: str = ""


class SearchResults(BaseModel):
    """Hits per section, plus how many each section actually has.

    The totals are separate from the lists because each section shows only its
    first few: "17 more articles" is the design's own affordance, and it needs a
    number the list itself cannot supply.
    """

    query: str
    articles: list[SearchHit] = Field(default_factory=list)
    pages: list[SearchHit] = Field(default_factory=list)
    media: list[SearchHit] = Field(default_factory=list)
    article_total: int = 0
    page_total: int = 0
    media_total: int = 0

    pages_more_url: str = ""
    media_more_url: str = ""
    """Where each section's "see all" goes.

    Sent rather than assembled in the screen because both land in pagebuilder,
    and how that module routes its own list and its media library is not
    something this one should be spelling out in TSX — see
    ``news.integrations.pagebuilder``.
    """

    @property
    def total(self) -> int:
        return self.article_total + self.page_total + self.media_total
