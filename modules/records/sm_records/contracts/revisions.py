"""Revision DTOs — the record-history half of the read contract.

Split out of ``contracts/schemas.py`` for the 300-line cap; that module
re-exports every name here so existing imports keep working. The seam is the
same one the endpoints already draw: ``schemas.py`` is "what does a row look
like on the wire", this is "what does one snapshot of it look like".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import SQLModel

from sm_records.models import RecordRevision

__all__ = [
    "RecordRevisionDetailRead",
    "RecordRevisionRestoreRequest",
    "RevisionListResponse",
    "RevisionRead",
    "record_revision_detail_read",
    "revision_read",
]


class RevisionRead(SQLModel):
    id: int
    version: int
    schema_version: int
    event: str
    display_title: str
    created_at: datetime
    created_by: str | None


class RevisionListResponse(SQLModel):
    items: list[RevisionRead]


class RecordRevisionDetailRead(RevisionRead):
    """``GET .../revisions/{id}``'s response — the list entry plus the
    payload it snapshotted, for the read-only preview before restoring it."""

    data: dict[str, Any]


class RecordRevisionRestoreRequest(SQLModel):
    expected_version: int


def revision_read(revision: RecordRevision) -> RevisionRead:
    return RevisionRead(
        id=revision.id,
        version=revision.version,
        schema_version=revision.schema_version,
        event=revision.event.value,
        display_title=revision.display_title,
        created_at=revision.created_at,
        created_by=revision.created_by,
    )


def record_revision_detail_read(revision: RecordRevision) -> RecordRevisionDetailRead:
    return RecordRevisionDetailRead(
        id=revision.id,
        version=revision.version,
        schema_version=revision.schema_version,
        event=revision.event.value,
        display_title=revision.display_title,
        created_at=revision.created_at,
        created_by=revision.created_by,
        data=dict(revision.data or {}),
    )
