"""A filename-pattern regroup of a big collection: the durable record a worker
and reconcile advance chunk by chunk.

Images are walked by ``(created_at, id)``; ``cursor_id`` is the last image of
the last committed chunk. A chunk's assignments, its counters and the cursor
move commit in one transaction that is fenced on ``generation`` and on the
previous cursor, so a runner that was replaced (reconcile's claim, a cancel)
stops at its next write and nothing is counted twice. At most one job per
collection is unfinished (``uq_images_regroup_job_active``).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import Boolean, Column, ForeignKey, Index, String, Uuid, text
from sqlmodel import Field

from sm_images.models._base import Base
from sm_images.models._cols import dt_col, fk_uuid, pk_uuid

ACTIVE_INDEX = "uq_images_regroup_job_active"
_UNFINISHED = text("finished_at IS NULL")

RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"


def _count() -> int:
    return Field(default=0, sa_column_kwargs={"nullable": False})


class RegroupJob(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_regroup_job"
    __table_args__ = (
        Index(
            ACTIVE_INDEX,
            "collection_id",
            unique=True,
            sqlite_where=_UNFINISHED,
            postgresql_where=_UNFINISHED,
        ),
    )

    id: uuid.UUID = pk_uuid()
    collection_id: uuid.UUID = fk_uuid("images_collection.id", ondelete="CASCADE")
    pattern: str = Field(max_length=500)
    reassign: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    dry_run: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    status: str = Field(
        default=RUNNING, sa_column=Column(String(12), nullable=False, default=RUNNING)
    )
    generation: int = _count()
    """Fences a stale runner after reconcile's claim or a cancel."""
    run_as: str | None = Field(default=None, max_length=255)
    """Whose edit right the job runs under; workers re-check it (``imports.access``)."""
    access_basis: str | None = Field(default=None, max_length=10)
    cursor_at: datetime | None = dt_col()
    cursor_id: uuid.UUID | None = Field(default=None, sa_column=Column(Uuid, nullable=True))
    scanned: int = _count()
    matched: int = _count()
    no_match: int = _count()
    timed_out: int = _count()
    already_grouped: int = _count()
    unchanged: int = _count()
    assigned: int = _count()
    groups_created: int = _count()
    groups_existing: int = _count()
    relaunches: int = _count()
    progress_mark: int = _count()
    """``scanned`` at the last relaunch: the poison-job breaker's reference."""
    error_code: str | None = Field(default=None, max_length=50)
    heartbeat_at: datetime | None = dt_col(index=True)
    finished_at: datetime | None = dt_col()


class RegroupJobGroup(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    """A pre-existing group a regroup job has used: what makes the job's
    ``groups_existing`` a count of distinct groups across chunks and resumes."""

    __tablename__ = "images_regroup_job_group"

    job_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid, ForeignKey("images_regroup_job.id", ondelete="CASCADE"), primary_key=True
        )
    )
    group_id: uuid.UUID = Field(
        sa_column=Column(Uuid, ForeignKey("images_group.id", ondelete="CASCADE"), primary_key=True)
    )
