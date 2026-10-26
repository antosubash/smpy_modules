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
    LocalesResponse,
    PageCreate,
    PageDetail,
    PageListResponse,
    PageNoteRequest,
    PageRead,
    PageRejectRequest,
    PageScheduleRequest,
    PageTranslationCreate,
    PageTranslationRead,
    PageUpdate,
    PuckData,
    StatusFilter,
)
from pagebuilder.contracts.schemas._revisions import (
    BlockChange,
    MetadataChange,
    PageRestoreMarker,
    PageRevisionDetail,
    PageRevisionListResponse,
    PageRevisionRead,
    RestoredSection,
    RevisionDiffResponse,
)
from pagebuilder.contracts.schemas._snapshots import (
    ImportApplyResponse,
    ImportDecisionRequest,
    PendingImportRead,
    SectionLabels,
    SnapshotCapabilities,
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
    "PageRestoreMarker",
    "PageRevisionDetail",
    "PageRevisionListResponse",
    "PageRevisionRead",
    "PageScheduleRequest",
    "PageTranslationCreate",
    "PageTranslationRead",
    "PageUpdate",
    "PendingImportRead",
    "PuckData",
    "RestoredSection",
    "RevisionDiffResponse",
    "SectionLabels",
    "SnapshotCapabilities",
    "SnapshotCreateRequest",
    "SnapshotListResponse",
    "SnapshotRead",
    "StatusFilter",
]
