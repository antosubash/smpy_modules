"""DTOs for the News module — the public surface.

Split into three files, and re-exported here so every existing
``from news.contracts.schemas import X`` keeps working. The split is only about
the repo's 300-line cap: the module grew when articles stopped being a sidecar
and started carrying a body, a workflow and their own SEO.
"""

from __future__ import annotations

from news.contracts.schemas._article import (
    ArticleBodyUpdate,
    ArticleCounts,
    ArticleCreate,
    ArticleDetail,
    ArticleListResponse,
    ArticleRead,
    ArticleStatus,
    ArticleUpdate,
    CategoryCount,
    CategoryListResponse,
    RejectRequest,
    RevisionEvent,
    RevisionRead,
)
from news.contracts.schemas._search import SearchHit, SearchResults
from news.contracts.schemas._taxonomy import (
    ArticleTagsUpdate,
    CategoryAdminListResponse,
    CategoryCreate,
    CategoryDeleteResult,
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
    "ArticleBodyUpdate",
    "ArticleCounts",
    "ArticleCreate",
    "ArticleDetail",
    "ArticleListResponse",
    "ArticleRead",
    "ArticleStatus",
    "ArticleTagsUpdate",
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
    "SearchHit",
    "SearchResults",
    "TagCreate",
    "TagListResponse",
    "TagMerge",
    "TagMergeResult",
    "TagRead",
    "TagUpdate",
]
