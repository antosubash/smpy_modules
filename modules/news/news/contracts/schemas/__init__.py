"""DTOs for the News module — the public surface.

A package rather than one file, for the same reason pagebuilder's is: it
crossed the repo's 300-line cap. Import from ``news.contracts.schemas``
exactly as before; the split is not part of the contract.
"""

from __future__ import annotations

from news.contracts.schemas._articles import (
    ArticleCounts,
    ArticleCreate,
    ArticleListResponse,
    ArticleRead,
    ArticleStatus,
    ArticleTagsUpdate,
    ArticleTranslationCreate,
    ArticleUpdate,
    ArticleWithPageCreate,
)
from news.contracts.schemas._search import (
    SearchHit,
    SearchResults,
)
from news.contracts.schemas._taxonomy import (
    CategoryAdminListResponse,
    CategoryCount,
    CategoryCreate,
    CategoryDeleteResult,
    CategoryListResponse,
    CategoryRead,
    CategoryReorder,
    CategoryUpdate,
    TagCreate,
    TagListResponse,
    TagMerge,
    TagMergeResult,
    TagRead,
    TagUpdate,
)

__all__ = [
    "ArticleCounts",
    "ArticleCreate",
    "ArticleListResponse",
    "ArticleRead",
    "ArticleStatus",
    "ArticleTagsUpdate",
    "ArticleTranslationCreate",
    "ArticleUpdate",
    "ArticleWithPageCreate",
    "CategoryAdminListResponse",
    "CategoryCount",
    "CategoryCreate",
    "CategoryDeleteResult",
    "CategoryListResponse",
    "CategoryRead",
    "CategoryReorder",
    "CategoryUpdate",
    "SearchHit",
    "SearchResults",
    "TagCreate",
    "TagListResponse",
    "TagMerge",
    "TagMergeResult",
    "TagRead",
    "TagUpdate",
]
