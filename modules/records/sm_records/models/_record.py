"""Records — the document table — and their revision log."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import uuid4

from simple_module_db.mixins import AuditMixin, SoftDeleteMixin
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, text
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

from sm_records.constants import MAX_DISPLAY_TITLE_LEN, MAX_SLUG_LEN
from sm_records.models._base import RECORD_TABLE, REVISION_TABLE, TYPE_TABLE, Base


def _new_uuid() -> str:
    return uuid4().hex


class RecordStatus(str, enum.Enum):  # noqa: UP042
    DRAFT = "draft"
    PUBLISHED = "published"


class RevisionEvent(str, enum.Enum):  # noqa: UP042
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"


class Record(Base, AuditMixin, SoftDeleteMixin, table=True):  # ty: ignore[unsupported-base]
    """One instance of a Record Type — YesSql's ``Document``.

    ``data`` is the payload and it is **never queried**: every filter and sort
    runs against the index tables (``_index.py``) and joins back here by
    primary key. The fixed columns on this row are the projection every record
    has regardless of its type — the module's ``ContentItemIndex``.

    ``SoftDeleteMixin`` and not ``MultiTenantMixin``: content deletion should
    be recoverable, and the framework's query filters already hide
    ``is_deleted`` rows. Tenancy is non-nullable at the DB and would force
    multi-tenancy on every host that installs the module.
    """

    __tablename__ = RECORD_TABLE
    __table_args__ = (
        Index("ix_records_record_type_status_position", "type_id", "status", "position"),
        # Partial unique: a slug is unique within its type, among rows that
        # have one. The index is on the row, not on live rows — a soft-deleted
        # record keeps its slug claimed, as pagebuilder does for trashed pages,
        # so a restore can never find its address taken.
        Index(
            "ix_records_record_type_slug",
            "type_id",
            "slug",
            unique=True,
            postgresql_where=text("slug IS NOT NULL"),
            sqlite_where=text("slug IS NOT NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    uuid: str = Field(default_factory=_new_uuid, max_length=32, unique=True, index=True)
    """The identifier used in relations and the public API, so an export /
    import round trip never depends on autoincrement."""

    type_id: int = Field(
        sa_column=Column(
            ForeignKey(f"{TYPE_TABLE}.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )

    data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    """The payload. History, not the query surface — design doc §7.2, §8.3."""

    schema_version: int = Field(sa_column_kwargs={"nullable": False})
    """Which ``RecordType.schema_version`` this row was last written against."""

    version: int = Field(default=1, sa_column_kwargs={"nullable": False})
    """Optimistic concurrency. Every write sends the version it read; a
    mismatch is a 409. Design doc §5.1."""

    status: RecordStatus = Field(
        default=RecordStatus.DRAFT,
        sa_column=Column(
            SAEnum(RecordStatus, name="records_record_status"),
            nullable=False,
            index=True,
        ),
    )
    slug: str | None = Field(default=None, max_length=MAX_SLUG_LEN)
    display_title: str = Field(default="", max_length=MAX_DISPLAY_TITLE_LEN)
    """Denormalised from ``RecordType.display_field`` on write, recomputed by
    the reindex, so the list screen never parses JSON to render a row."""
    position: int = Field(default=0, sa_column_kwargs={"nullable": False})
    published_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )


class RecordRevision(Base, table=True):  # ty: ignore[unsupported-base]
    """Append-only snapshot of a record's payload, one per write.

    Capped per record by ``revision_limit``; unbounded revisions on a busy
    type outgrow the document table itself.
    """

    __tablename__ = REVISION_TABLE
    __table_args__ = (Index("ix_records_revision_record_id", "record_id", "id"),)

    id: int | None = Field(default=None, primary_key=True)
    record_id: int = Field(
        sa_column=Column(ForeignKey(f"{RECORD_TABLE}.id", ondelete="CASCADE"), nullable=False)
    )
    schema_version: int = Field(sa_column_kwargs={"nullable": False})
    version: int = Field(sa_column_kwargs={"nullable": False})
    """The ``Record.version`` this snapshot *produced*."""
    data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    display_title: str = Field(default="", max_length=MAX_DISPLAY_TITLE_LEN)
    event: RevisionEvent = Field(
        sa_column=Column(SAEnum(RevisionEvent, name="records_revision_event"), nullable=False)
    )
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    created_by: str | None = Field(default=None, max_length=255)
