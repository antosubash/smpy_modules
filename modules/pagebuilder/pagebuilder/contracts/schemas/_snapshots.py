"""DTOs for content snapshots and the import approval gate."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from pagebuilder.contracts.schemas._fields import OptionalNote
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


class SectionLabels(BaseModel):
    """How the screens name a section registered on this host (#80).

    ``label_key`` and ``count_label_keys`` are the contributor's own catalogue
    keys, resolved by the client at render time.
    """

    section: str
    label_key: str
    count_label_keys: dict[str, str] = {}


class SnapshotCapabilities(BaseModel):
    """What the reader may do on the Import / Export screen.

    Sent by the server so the screen offers only the controls the API will
    accept: ``publish`` covers taking, uploading, downloading, deleting and
    staging a restore; ``approve`` covers deciding a staged one.
    """

    publish: bool = False
    approve: bool = False


class SnapshotListResponse(BaseModel):
    items: list[SnapshotRead]
    sections: list[SectionLabels] = []
    """The contributed sections registered here, to label each row's counts."""
    capabilities: SnapshotCapabilities = SnapshotCapabilities()


class SnapshotCreateRequest(BaseModel):
    note: OptionalNote = None


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
    note: OptionalNote = None


class ImportApplyResponse(BaseModel):
    """What an approved restore actually did."""

    pages_created: int
    pages_updated: int
    media_added: int
    redirects: int
    redirects_dropped: list[str]
    sections: dict[str, dict[str, int]] = {}
    """Per contributed section (#80), the counts its apply reported."""
    denied_sections: list[dict[str, Any]] = []
    """Contributed sections this restore skipped because the approver (or the
    stager) lacks the permissions they need: ``{section, label_key,
    reason_key, permissions}`` (#80)."""
