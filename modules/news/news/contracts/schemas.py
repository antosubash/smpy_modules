"""DTOs for the News module — the public surface."""

from __future__ import annotations

from datetime import datetime

from pagebuilder.models import PageStatus
from pydantic import BaseModel, Field

from news.constants import MAX_CATEGORY_LEN, MAX_TAG_LEN


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
    page_status: PageStatus
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


class ArticleUpdate(BaseModel):
    category: str | None = Field(default=None, max_length=MAX_CATEGORY_LEN)
    published_at: datetime | None = None
    pinned: bool | None = None
    show_in_feed: bool | None = None
    author: str | None = Field(default=None, max_length=120)


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
