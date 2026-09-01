"""DTOs for the pagebuilder module — the public surface.

A package rather than one file, for the same reason ``models`` is: it crossed
the repo's 300-line cap. Import from ``pagebuilder.contracts.schemas`` exactly
as before; the split is not part of the contract.
"""

from __future__ import annotations

from pagebuilder.contracts.schemas._layout import (
    LayoutDetail,
    LayoutRead,
    LayoutRevisionDetail,
    LayoutRevisionListResponse,
    LayoutRevisionRead,
    LayoutUpdate,
)
from pagebuilder.contracts.schemas._media import (
    MediaAssetDetail,
    MediaAssetListResponse,
    MediaAssetRead,
    MediaAssetUpdate,
    MediaAssetVariant,
    MediaUsage,
)
from pagebuilder.contracts.schemas._pages import (
    BlockChange,
    LocalesResponse,
    MetadataChange,
    PageCreate,
    PageDetail,
    PageListResponse,
    PageNoteRequest,
    PageRead,
    PageRejectRequest,
    PageRevisionDetail,
    PageRevisionListResponse,
    PageRevisionRead,
    PageScheduleRequest,
    PageTranslationCreate,
    PageTranslationRead,
    PageUpdate,
    PuckData,
    RevisionDiffResponse,
    StatusFilter,
)
from pagebuilder.contracts.schemas._snapshots import (
    ImportApplyResponse,
    ImportDecisionRequest,
    PendingImportRead,
    SnapshotCreateRequest,
    SnapshotListResponse,
    SnapshotRead,
)

__all__ = [
    "BlockChange",
    "ImportApplyResponse",
    "ImportDecisionRequest",
    "LayoutDetail",
    "LayoutRead",
    "LayoutRevisionDetail",
    "LayoutRevisionListResponse",
    "LayoutRevisionRead",
    "LayoutUpdate",
    "LocalesResponse",
    "MediaAssetDetail",
    "MediaAssetListResponse",
    "MediaAssetRead",
    "MediaAssetUpdate",
    "MediaAssetVariant",
    "MediaUsage",
    "MetadataChange",
    "PageCreate",
    "PageDetail",
    "PageListResponse",
    "PageNoteRequest",
    "PageRead",
    "PageRejectRequest",
    "PageRevisionDetail",
    "PageRevisionListResponse",
    "PageRevisionRead",
    "PageScheduleRequest",
    "PageTranslationCreate",
    "PageTranslationRead",
    "PageUpdate",
    "PendingImportRead",
    "PuckData",
    "RevisionDiffResponse",
    "SnapshotCreateRequest",
    "SnapshotListResponse",
    "SnapshotRead",
    "StatusFilter",
]
