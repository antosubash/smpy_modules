"""DTOs for content snapshots and the import approval gate."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pagebuilder.models import ImportStatus, SnapshotSource


class SnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    note: str | None
    source: SnapshotSource
    format_version: int
    manifest: dict[str, Any]
    size_bytes: int
    created_at: datetime | None = None
    created_by: str | None = None


class SnapshotListResponse(BaseModel):
    items: list[SnapshotRead]


class SnapshotCreateRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class PendingImportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    snapshot_id: int
    plan: dict[str, Any]
    status: ImportStatus
    note: str | None
    created_at: datetime | None = None
    created_by: str | None = None
    decided_at: datetime | None = None
    decided_by: str | None = None


class ImportDecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ImportApplyResponse(BaseModel):
    """What an approved restore actually did."""

    pages_created: int
    pages_updated: int
    media_added: int
    redirects: int
    redirects_dropped: list[str]
