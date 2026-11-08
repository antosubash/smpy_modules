"""Bodies and answers of the import API (Task 10's client mirrors these)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints
from sm_records.contracts.newsletter_import import ImportTargets

from sm_newsletter.core.constants import MAX_TYPE_KEY_LEN
from sm_newsletter.imports.constants import KEEP_ERRORS
from sm_newsletter.models import ImportJob

__all__ = [
    "ERRORS_SHOWN",
    "ImportOut",
    "ImportPatch",
    "ImportSummaryOut",
    "ListCreate",
    "to_out",
]

ERRORS_SHOWN = 50
"""Row errors in ``ImportOut``; the CSV has up to ``KEEP_ERRORS``."""
assert ERRORS_SHOWN <= KEEP_ERRORS


class ListCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Annotated[str, StringConstraints(min_length=1, max_length=MAX_TYPE_KEY_LEN)]
    label: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class ImportPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping: Any


class ImportFileOut(BaseModel):
    name: str
    kind: str
    rows: int


class ImportColumnOut(BaseModel):
    index: int
    header: str


class ImportTagOut(BaseModel):
    label: str
    value: str
    count: int


class ImportErrorOut(BaseModel):
    file: int | None = None
    line: int | None = None
    code: str
    field: str | None = None


class ImportFieldOut(BaseModel):
    key: str
    label: str
    type: str


class ImportTargetsOut(BaseModel):
    fields: list[ImportFieldOut]
    tags: str


class ImportOut(BaseModel):
    id: int
    list_type_key: str
    status: str
    files: list[ImportFileOut]
    columns: list[ImportColumnOut]
    mapping: dict[str, Any]
    targets: ImportTargetsOut
    tags_found: list[ImportTagOut]
    total: int
    duplicates: int
    invalid: int
    processed: int
    created: int
    updated: int
    skipped: int
    suppressed: int
    failed: int
    errors: list[ImportErrorOut]
    errors_total: int
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ImportSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    list_type_key: str
    status: str
    total: int
    processed: int
    created_at: datetime


def to_out(job: ImportJob, targets: ImportTargets) -> ImportOut:
    """``job`` as the API shows it; ``targets`` is read live, so a field removed since
    staging is gone from the choices."""
    data = {
        name: getattr(job, name)
        for name in (
            *("id", "list_type_key", "status", "mapping", "total", "duplicates", "invalid"),
            *("processed", "created", "updated", "skipped", "suppressed", "failed"),
            *("errors_total", "error_code", "created_at", "started_at", "finished_at"),
        )
    }
    return ImportOut(
        **data,
        files=[ImportFileOut(**f) for f in job.files],
        columns=[
            ImportColumnOut(index=i, header=str(c.get("header", "")))
            for i, c in enumerate(job.columns)
        ],
        targets=ImportTargetsOut(
            fields=[ImportFieldOut(key=f.key, label=f.label, type=f.type) for f in targets.fields],
            tags=targets.tags,
        ),
        tags_found=[ImportTagOut(**t) for t in job.tags_found],
        errors=[ImportErrorOut(**e) for e in job.errors[:ERRORS_SHOWN]],
    )
