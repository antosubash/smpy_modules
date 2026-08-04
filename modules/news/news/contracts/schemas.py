"""DTOs for the News module — the public surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from news.constants import MAX_CATEGORY_LEN


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
    url: str
    """Where the article actually serves.

    An article *is* a page, so this is the page's own public URL rather than a
    route this module owns — duplicating the public viewer would mean
    duplicating its ETag, cache, CSP, SEO and site-layout handling.
    """


class ArticleListResponse(BaseModel):
    items: list[ArticleRead]
    total: int


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


class ArticleUpdate(BaseModel):
    category: str | None = Field(default=None, max_length=MAX_CATEGORY_LEN)
    published_at: datetime | None = None
