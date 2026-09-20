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

from sm_records.constants import (
    DEFAULT_CONTENT_LOCALE,
    MAX_DISPLAY_TITLE_LEN,
    MAX_LOCALE_LEN,
    MAX_SLUG_LEN,
    TRANSLATION_GROUP_LEN,
)
from sm_records.models._base import RECORD_TABLE, REVISION_TABLE, TYPE_TABLE, Base

SLUG_INDEX_NAME = "ix_records_record_type_slug"
"""The partial unique index of §5, named here because two layers need it: the
table definition below, and :func:`sm_records.services._claims.flush_write`,
which recognises the database's own refusal and raises the 409 the application
check raises. A rename that reached only one of them would turn every lost slug
race back into a 500, so the name has one owner."""

GROUP_LOCALE_INDEX_NAME = "ix_records_record_group_locale"
"""One record per language per translation group (Phase 5 §4.3), named for the
same reason :data:`SLUG_INDEX_NAME` is: :func:`sm_records.services._claims.flush_write`
recognises the database's own refusal and raises the 409 the application check
raises."""

SLUG_CONFLICT_SIGNATURES: tuple[str, ...] = (
    SLUG_INDEX_NAME,
    f"{RECORD_TABLE}.type_id, {RECORD_TABLE}.locale, {RECORD_TABLE}.slug",
)
"""How each backend says "that slug is taken" in an ``IntegrityError``.

Two spellings because the two dialects report a different thing. Postgres
names the constraint (``duplicate key value violates unique constraint
"ix_records_record_type_slug"``); SQLite names the *columns*
(``UNIQUE constraint failed: records_record.type_id, records_record.locale,
records_record.slug``) and never mentions the index at all. The column list is
therefore part of this contract: adding ``locale`` to the index — which is what
makes the same word an address in two languages (Phase 5 §4.1) — changes what
SQLite prints, and a signature left at the old pair would turn every lost slug
race on SQLite back into a 500. Matching the driver's whole message shape
would be worse than either — this matches the one substring each backend does
put in it, and anything matching neither is re-raised, because an
``IntegrityError`` this module cannot explain is a bug rather than a 409."""

GROUP_LOCALE_CONFLICT_SIGNATURES: tuple[str, ...] = (
    GROUP_LOCALE_INDEX_NAME,
    f"{RECORD_TABLE}.translation_group, {RECORD_TABLE}.locale",
)
"""The same two spellings for "that language is already taken in this group".

Reached only by a writer that sets ``translation_group`` itself — an import
carrying the column, or a second ``POST /translations`` that lost the race with
the first. :func:`sm_records.services._translations.create_translation` checks
for the sibling first; this is what closes the window behind it, and it costs
the ordinary write path nothing because the string comparison happens only
after a flush has already failed."""


def new_uuid() -> str:
    """A record's public identifier, and — for a record with no siblings — its
    own translation group. Exported because :func:`create_record` needs both
    values to be *the same* string (Phase 5 §4.1), which it cannot arrange by
    letting two ``default_factory`` calls fire independently."""
    return uuid4().hex


_new_uuid = new_uuid


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
        # Partial unique: a slug is unique within its type **and its locale**,
        # among rows that have one. ``locale`` is in the key rather than beside
        # it because the alternative — a locale column whose slugs are still
        # globally unique per type — is precisely the half-version the original
        # design warned about, the one where ``?locale=de`` starts serving the
        # English record (Phase 5 §4.1). The index is on the row, not on live rows — a soft-deleted
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
            "locale",
            "slug",
            unique=True,
            postgresql_where=text("slug IS NOT NULL"),
            sqlite_where=text("slug IS NOT NULL"),
        ),
        # One record per language per translation group (Phase 5 §4.3). A
        # second "add German" — a double submit, a stale tab, two rows of an
        # import sharing a group — otherwise produces two German siblings and
        # every language switcher starts contradicting itself. Trashed rows are
        # included, deliberately: a sibling in the trash still claims its slug
        # in its locale, so the language is occupied until it is purged.
        Index(GROUP_LOCALE_INDEX_NAME, "translation_group", "locale", unique=True),
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
    locale: str = Field(default=DEFAULT_CONTENT_LOCALE, max_length=MAX_LOCALE_LEN)
    """The language this record is written in, **fixed for its lifetime**.

    Every record has one, including on a monolingual install: a nullable column
    would mean every slug lookup had to spell "this locale or nothing", and the
    row that predates the feature would be the one that behaves differently.
    There is no ``locale`` on ``RecordUpdate`` — moving a record between
    languages would strand its slug in the old one, so the only way to have the
    same content in two languages is ``POST /records/{uuid}/translations``,
    which creates a sibling (Phase 5 §4.3).

    The default is the literal ``"en"`` and not the configured
    ``default_content_locale``: this is a column default the ORM applies with
    no request and no ``app.state`` in reach, and the write path
    (``services.records.create_record``) resolves the configured value itself.
    """

    translation_group: str = Field(
        default_factory=new_uuid, max_length=TRANSLATION_GROUP_LEN, index=True
    )
    """What a record and its translations share.

    A generated key rather than a pointer at "the original", because there is
    no original: translations are siblings, and pointing each at a source would
    make deleting the English record orphan the German one — or quietly
    re-parent it. ``create_record`` sets it to the record's **own uuid**, so a
    record with no siblings is alone in a group named after itself; a record
    created through ``POST /translations`` joins the source's group instead.
    Deleting a record never touches its siblings: a group is a grouping, not a
    cascade.
    """
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
