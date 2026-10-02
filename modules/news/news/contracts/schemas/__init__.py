"""DTOs for the News module — the public surface.

A package rather than one file, for the same reason pagebuilder's is: it
crossed the repo's 300-line cap when articles stopped being a sidecar and
started carrying a body, a workflow, their own SEO and their own language.
Import from ``news.contracts.schemas`` exactly as before; the split is not part
of the contract.
"""

from __future__ import annotations

from news.contracts.schemas._articles import (
    ArticleCounts,
    ArticleDetail,
    ArticleListResponse,
    ArticleRead,
    ArticleStatus,
    RevisionEvent,
    RevisionRead,
)
from news.contracts.schemas._search import SearchHit, SearchResults
from news.contracts.schemas._taxonomy import (
    ArticleTagsUpdate,
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
from news.contracts.schemas._writes import (
    ArticleBodyUpdate,
    ArticleCreate,
    ArticleTranslationCreate,
    ArticleUpdate,
    RejectRequest,
    ScheduleRequest,
)

__all__ = [
    "ArticleBodyUpdate",
    "ArticleCounts",
    "ArticleCreate",
    "ArticleDetail",
    "ArticleListResponse",
    "ArticleRead",
    "ArticleStatus",
    "ArticleTagsUpdate",
    "ArticleTranslationCreate",
    "ArticleUpdate",
    "CategoryAdminListResponse",
    "CategoryCount",
    "CategoryCreate",
    "CategoryDeleteResult",
    "CategoryListResponse",
    "CategoryRead",
    "CategoryReorder",
    "CategoryUpdate",
    "RejectRequest",
    "RevisionEvent",
    "RevisionRead",
    "ScheduleRequest",
    "SearchHit",
    "SearchResults",
    "TagCreate",
    "TagListResponse",
    "TagMerge",
    "TagMergeResult",
    "TagRead",
    "TagUpdate",
]
