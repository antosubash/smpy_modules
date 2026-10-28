"""Responses of the import API. The staged object keys and who started the job
are never part of a response."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from sm_images.models import ImportJob

__all__ = ["ImportJobOut", "ImportJobPage", "job_out"]


class ImportJobOut(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    kind: str
    status: str
    mapping: dict[str, Any]
    source_url: str | None
    total_count: int
    checkpoint_index: int
    done_count: int
    duplicate_count: int
    failed_count: int
    errors: list[dict[str, Any]]
    auto_run_prompts: bool
    created_at: datetime
    updated_at: datetime | None
    heartbeat_at: datetime | None


class ImportJobPage(BaseModel):
    items: list[ImportJobOut]


def job_out(row: ImportJob) -> ImportJobOut:
    return ImportJobOut(
        id=row.id,
        collection_id=row.collection_id,
        kind=row.kind.value,
        status=row.status.value,
        mapping=dict(row.mapping or {}),
        source_url=row.source_url,
        total_count=row.total_count,
        checkpoint_index=row.checkpoint_index,
        done_count=row.done_count,
        duplicate_count=row.duplicate_count,
        failed_count=row.failed_count,
        errors=list(row.errors or []),
        auto_run_prompts=row.auto_run_prompts,
        created_at=row.created_at,
        updated_at=row.updated_at,
        heartbeat_at=row.heartbeat_at,
    )
