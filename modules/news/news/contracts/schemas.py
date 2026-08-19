"""DTOs for the News module — the public surface."""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field

from news.constants import MAX_CATEGORY_LEN, MAX_TITLE_LEN


class ArticleStatus(str, enum.Enum):  # noqa: UP042
    """Workflow state of the page behind an article.

    News' own enum, deliberately, even though the values are pagebuilder's
    ``PageStatus`` verbatim. A DTO is a contract with this module's callers,
    and re-exporting a neighbour's enum through it made every consumer — the
    OpenAPI schema, the TypeScript client — depend on pagebuilder's package
    layout to name a value news is perfectly able to name itself.

    The values match, so the wire format is unchanged and the mapping in
    ``integrations.pagebuilder.article_status`` is total by construction.
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


class ArticleListResponse(BaseModel):
    items: list[ArticleRead]
    total: int


class CategoryCount(BaseModel):
    category: str
    count: int


class CategoryListResponse(BaseModel):
    items: list[CategoryCount]

    uncategorised: int = 0
    """How many articles carry no category at all.

    Its own field rather than an item with a blank name: a blank category is
    not a category, and as a list entry it would be indistinguishable from the
    "All" option in the filter row. Editors need it because an uncategorised
    article is usually one somebody forgot to finish.
    """


class ArticleCreate(BaseModel):
    """Attach article metadata to an existing page."""

    page_id: int
    category: str = Field(default="", max_length=MAX_CATEGORY_LEN)
    published_at: datetime | None = None


class ArticleWithPageCreate(BaseModel):
    """Create the page *and* attach the article to it, in one request.

    The two-call version of this ran in the browser and could only be
    half-done: if attaching failed after the page was created, an empty
    articleless page was left behind with nothing to clean it up.
    """

    title: str = Field(min_length=1, max_length=MAX_TITLE_LEN)
    category: str = Field(default="", max_length=MAX_CATEGORY_LEN)
    published_at: datetime | None = None


class ArticleUpdate(BaseModel):
    category: str | None = Field(default=None, max_length=MAX_CATEGORY_LEN)
    published_at: datetime | None = None
