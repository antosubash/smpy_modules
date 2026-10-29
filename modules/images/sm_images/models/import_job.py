"""Import jobs: a GeoJSON feed or a zip, resumable from ``checkpoint_index``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import BigInteger, Column, Uuid
from sqlmodel import Field

from sm_images.models._base import Base
from sm_images.models._cols import dt_col, enum_col, fk_uuid, json_col, pk_uuid
from sm_images.models.enums import ImportKind, JobStatus


class ImportJob(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_import_job"

    id: uuid.UUID = pk_uuid()
    collection_id: uuid.UUID = fk_uuid("images_collection.id")
    kind: ImportKind = enum_col(ImportKind, "import_kind", ImportKind.GEOJSON_URL)
    status: JobStatus = enum_col(JobStatus, "job_status", JobStatus.PENDING)
    mapping: dict[str, Any] = json_col(dict)
    """url, image, lat, lng, datetime, external_id and group-key properties; filename pattern."""
    source_key: str | None = Field(default=None, max_length=500)
    """The staged GeoJSON; cleared once a terminal job has deleted it."""
    source_url: str | None = Field(default=None, max_length=2000)
    """Where the source was fetched from (``safe_stream``); lets a restart re-stage it."""
    staged_keys: list[str] = json_col(list)
    """Every object this job staged, so cancel and the janitor can delete exactly these."""
    upload_session_id: uuid.UUID | None = Field(default=None, sa_column=Column(Uuid, nullable=True))
    """A ZIP import's ``images_upload_session``: the archive's multipart upload."""
    source_etag: str | None = Field(default=None, max_length=200)
    """A ZIP's fingerprint at the seal (the backend's etag, or one derived from
    its parts); extraction refuses an object that no longer matches."""
    source_size: int | None = Field(default=None, sa_type=BigInteger)
    """A ZIP's size at the seal, in bytes."""
    reset_mode: str | None = Field(default=None, max_length=20)
    """While ``resetting``: ``restart`` or ``retry``, so reconcile can resume it."""
    generation: int = Field(default=0, sa_column_kwargs={"nullable": False})
    """Fences a stale runner after a resume."""
    heartbeat_at: datetime | None = dt_col(index=True)
    relaunches: int = Field(default=0, sa_column_kwargs={"nullable": False})
    """Reconcile relaunches since the job last made progress (the poison-job
    breaker, ``recover.RELAUNCH_LIMIT``); an operator's control resets it."""
    progress_mark: int = Field(default=0, sa_column_kwargs={"nullable": False})
    """:func:`~sm_images.imports.jobs.progress` at the last relaunch."""
    reset_progress: int = Field(default=0, sa_column_kwargs={"nullable": False})
    """Items reset so far (restart, retry-failed): a reset's own progress."""
    checkpoint_index: int = Field(default=0, sa_column_kwargs={"nullable": False})
    total_count: int = Field(default=0, sa_column_kwargs={"nullable": False})
    done_count: int = Field(default=0, sa_column_kwargs={"nullable": False})
    duplicate_count: int = Field(default=0, sa_column_kwargs={"nullable": False})
    failed_count: int = Field(default=0, sa_column_kwargs={"nullable": False})
    errors: list[dict[str, Any]] = json_col(list)
    """Capped list of per-item errors."""
    auto_run_prompts: bool = Field(default=False)
