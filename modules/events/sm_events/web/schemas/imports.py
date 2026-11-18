"""Import request bodies (bounded) and responses (not). Never the file or an item's payload."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

__all__ = ["ApplyIn", "CalendarRef", "ImportItemOut", "ImportItemPage", "ImportOut", "ImportPage"]


class ApplyIn(BaseModel):
    publish: bool = False


class CalendarRef(BaseModel):
    id: uuid.UUID
    name: str


class ImportOut(BaseModel):
    id: int
    calendar: CalendarRef
    status: str
    filename: str
    size_bytes: int
    total: int
    counts: dict[str, int]
    reasons: dict[str, int]
    dropped: dict[str, int]
    created: int
    updated: int
    unchanged: int
    skipped: int
    failed: int
    processed: int
    error_code: str | None
    publish: bool
    created_at: datetime
    finished_at: datetime | None


class ImportPage(BaseModel):
    items: list[ImportOut]
    total: int


class ImportItemOut(BaseModel):
    seq: int
    uid: str
    verdict: str
    reason: str | None
    notes: list[str]
    title: str
    starts_at: datetime | None
    all_day: bool
    recurring: bool
    outcome: str | None
    outcome_code: str | None
    event_id: uuid.UUID | None


class ImportItemPage(BaseModel):
    items: list[ImportItemOut]
    total: int
    page: int
    page_size: int


def _ints(value: Any) -> dict[str, int]:
    return {str(k): int(v) for k, v in (value or {}).items()}


def import_out(row: Any, calendar: CalendarRef) -> ImportOut:
    """An ``EventImport`` as the API shows it: no ``source``, no grants, nothing of the file."""
    return ImportOut(
        id=row.id,
        calendar=calendar,
        status=row.status,
        filename=row.filename,
        size_bytes=row.size_bytes,
        total=row.total,
        counts=_ints(row.counts),
        reasons=_ints(row.reasons),
        dropped=_ints(row.dropped),
        created=row.created,
        updated=row.updated,
        unchanged=row.unchanged,
        skipped=row.skipped,
        failed=row.failed,
        processed=row.processed,
        error_code=row.error_code,
        publish=row.publish,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )
