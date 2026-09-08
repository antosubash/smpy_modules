"""Categories and tags — the two ways articles are grouped."""

from __future__ import annotations

from pydantic import BaseModel, Field

from news.constants import MAX_CATEGORY_LEN, MAX_TAG_LEN


class CategoryCount(BaseModel):
    category: str
    count: int


class CategoryListResponse(BaseModel):
    items: list[CategoryCount]


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

