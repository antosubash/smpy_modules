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

SLUG_INDEX_NAME = "ix_records_record_type_slug"
"""The partial unique index of §5, named here because two layers need it: the
table definition below, and :func:`sm_records.services._claims.flush_write`,
which recognises the database's own refusal and raises the 409 the application
check raises. A rename that reached only one of them would turn every lost slug
race back into a 500, so the name has one owner."""

SLUG_CONFLICT_SIGNATURES: tuple[str, ...] = (
    SLUG_INDEX_NAME,
    f"{RECORD_TABLE}.type_id, {RECORD_TABLE}.slug",
)
"""How each backend says "that slug is taken" in an ``IntegrityError``.

Two spellings because the two dialects report a different thing. Postgres
names the constraint (``duplicate key value violates unique constraint
"ix_records_record_type_slug"``); SQLite names the *columns*
(``UNIQUE constraint failed: records_record.type_id, records_record.slug``)
and never mentions the index at all. Matching the driver's whole message shape
would be worse than either — this matches the one substring each backend does
put in it, and anything matching neither is re-raised, because an
``IntegrityError`` this module cannot explain is a bug rather than a 409."""


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
        # One composite per sortable fixed column, all shaped
        # ``(type_id, <column>, id)``. A list page is always narrowed to one
        # type and always ends its ``ORDER BY`` with ``Record.id`` (the
        # tiebreaker that makes a page boundary deterministic and a cursor
        # unambiguous), so this is the exact key the order needs: SQLite and
        # Postgres can both walk it and stop after ``page_size`` rows instead
        # of sorting the whole type into a temp B-tree.
        #
        # Two things have to stay true for them to be used, and both are in
        # ``index/_sorting.py``: the ordering must not wear ``NULLS LAST`` on
        # a column the database knows is ``NOT NULL`` (it is not the order a
        # btree stores), and the tiebreaker must be ``id`` and nothing else.
        #
        # ``display_title`` earns its own for a second reason: it is what the
        # relation picker searches, and a prefix match over a covering index
        # is the difference between reading three columns of an index and
        # reading every row of the type.
        #
        # They are not free — six more btree inserts per record written. That
        # is the trade §7.3 already makes for every indexed field, made once
        # more for the projection every record has.
        Index("ix_records_record_type_position_id", "type_id", "position", "id"),
        Index("ix_records_record_type_published_id", "type_id", "published_at", "id"),
        Index("ix_records_record_type_updated_id", "type_id", "updated_at", "id"),
        Index("ix_records_record_type_created_id", "type_id", "created_at", "id"),
        Index("ix_records_record_type_title_id", "type_id", "display_title", "id"),
        Index("ix_records_record_type_slug_id", "type_id", "slug", "id"),
        # Partial unique: a slug is unique within its type, among rows that
        # have one. The index is on the row, not on live rows — a soft-deleted
        # record keeps its slug claimed, as pagebuilder does for trashed pages,
        # so a restore can never find its address taken.
        #
        # Alembic autogenerate does not compare an index's ``WHERE``: it sees
        # the name and the columns and reports no change. So if this predicate
        # is edited — or the deployed index was created without one — nothing
        # will tell you. ``SM010``/``SM011`` are about revisions and tables and
        # are equally blind to it. Changing the predicate therefore means
        # hand-writing the drop-and-recreate into a revision, and verifying the
        # deployed definition (``\di+`` / ``sqlite_master``) rather than
        # trusting a clean autogenerate.
        Index(
            SLUG_INDEX_NAME,
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
