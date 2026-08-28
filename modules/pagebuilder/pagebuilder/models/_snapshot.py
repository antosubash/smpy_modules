"""Snapshots of the whole site, and the approval gate in front of restoring one."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from simple_module_db.mixins import AuditMixin
from sqlalchemy import JSON, Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

from pagebuilder.models._base import Base

SNAPSHOT_TABLE = "pagebuilder_snapshots"


class SnapshotSource(str, enum.Enum):  # noqa: UP042 — see PageStatus
    """Where a snapshot came from.

    One store rather than three: *upload a bundle from prod* and *roll back to
    yesterday* differ only in this column, which is what keeps restore a single
    code path instead of two that drift apart.
    """

    MANUAL = "manual"
    UPLOAD = "upload"
    PRE_RESTORE = "pre_restore"


class ImportStatus(str, enum.Enum):  # noqa: UP042 — see PageStatus
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ContentSnapshot(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """One captured state of the site's pagebuilder content.

    The documents live as JSON files under ``snapshot_root``; this row holds
    only what the listing renders, so drawing the screen never opens a file.
    """

    __tablename__ = SNAPSHOT_TABLE

    id: int | None = Field(default=None, primary_key=True)
    note: str | None = Field(default=None, max_length=2000)
    source: SnapshotSource = Field(
        default=SnapshotSource.MANUAL,
        sa_column=Column(
            SAEnum(SnapshotSource, name="pagebuilder_snapshot_source"),
            nullable=False,
            index=True,
        ),
    )
    format_version: int = Field(default=1)
    manifest: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    size_bytes: int = Field(default=0)


class SnapshotMedia(Base, table=True):  # ty: ignore[unsupported-base]
    """A blob this snapshot references.

    Reference-counted deletion reads this table alone: dropping a snapshot must
    never mean opening every other snapshot's index to work out which bytes are
    still spoken for.
    """

    __tablename__ = "pagebuilder_snapshot_media"

    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: int = Field(
        foreign_key=f"{SNAPSHOT_TABLE}.id", index=True, ondelete="CASCADE"
    )
    sha256: str = Field(max_length=64, index=True)
    bundle_name: str = Field(max_length=300)
    original_filename: str = Field(max_length=300)
    content_type: str = Field(max_length=120)
    folder: str | None = Field(default=None, max_length=300)


class PendingImport(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """A staged restore waiting on an approver.

    At most one row is ``PENDING`` at a time. A plan computed against content
    that has since changed misrepresents what applying would do, and keeping the
    plan singular is the cheapest way to keep it honest.
    """

    __tablename__ = "pagebuilder_pending_imports"

    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: int = Field(
        foreign_key=f"{SNAPSHOT_TABLE}.id", index=True, ondelete="CASCADE"
    )
    plan: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    status: ImportStatus = Field(
        default=ImportStatus.PENDING,
        sa_column=Column(
            SAEnum(ImportStatus, name="pagebuilder_import_status"),
            nullable=False,
            index=True,
        ),
    )
    note: str | None = Field(default=None, max_length=2000)
    decided_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    decided_by: str | None = Field(default=None, max_length=200)
