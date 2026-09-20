"""Records — the document table — and their revision log, as a factory.

One call builds one table set (Phase 5 §6): the global set is
:func:`make_record_tables` with the ``records_`` prefix, and a declared
collection is the same call with ``records_c_<name>_``. Writing the columns
once is what makes "a collection's tables are identical in shape to the global
ones" a property of the code rather than of two definitions agreeing —
``tests/test_collections_ddl.py`` compares the emitted DDL to prove it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from simple_module_db.mixins import AuditMixin, SoftDeleteMixin
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from sm_records.constants import (
    DEFAULT_CONTENT_LOCALE,
    MAX_DISPLAY_TITLE_LEN,
    MAX_LOCALE_LEN,
    MAX_SLUG_LEN,
    TRANSLATION_GROUP_LEN,
)
from sm_records.models._base import RECORD_SUFFIX, REVISION_SUFFIX, TYPE_TABLE, Base
from sm_records.models._factory import table_class
from sm_records.models._record_args import add_descending_indexes, record_args


def new_uuid() -> str:
    """A record's public identifier, and — for a record with no siblings — its
    own translation group. Exported because :func:`create_record` needs both
    values to be *the same* string (Phase 5 §4.1), which it cannot arrange by
    letting two ``default_factory`` calls fire independently.

    It is a uuid4 hex, and that is what makes a uuid **globally unique across
    collections** in practice (Phase 5 §6.4). Each record table carries its own
    unique index, so nothing at the database level stops one uuid appearing in
    two collections; nothing at the generator level makes it plausible, and the
    importer generates uuids the same way. The README says so out loud, because
    the cross-collection reads below (referrers, ``?expand=``) resolve a target
    by uuid and would otherwise be relying on it silently.
    """
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


_RECORD_DOC = """One instance of a Record Type — YesSql's ``Document``.

``data`` is the payload and it is **never queried**: every filter and sort runs
against the index tables (``_index.py``) and joins back here by primary key.
The fixed columns on this row are the projection every record has regardless of
its type — the module's ``ContentItemIndex``.

``SoftDeleteMixin`` and not ``MultiTenantMixin``: content deletion should be
recoverable, and the framework's query filters already hide ``is_deleted`` rows
— including on a **collection's** table, because that filter is attached per
mapper by ``issubclass(cls, SoftDeleteMixin)`` (``simple_module_db.listeners``)
and a generated class inherits the mixin like any other, with nothing to
register. Tenancy is non-nullable at the DB and would force multi-tenancy on
every host that installs the module."""

_REVISION_DOC = """Append-only snapshot of a record's payload, one per write.

Capped per record by ``revision_limit``; unbounded revisions on a busy type
outgrow the document table itself."""


@dataclass(frozen=True, slots=True)
class RecordTables:
    """One table set's document half, and the index names two layers read back.

    The names travel with the classes rather than sitting at module scope
    because a collection's indexes are named after *its* tables, and the 409
    that :func:`sm_records.services._claims.flush_write` raises is recognised by
    matching the database's own words. A signature left at the global spelling
    would turn every lost slug race inside a collection back into a 500 —
    which is the same failure the global signatures were added to fix.
    """

    record: type
    revision: type
    slug_index: str
    group_locale_index: str
    slug_signatures: tuple[str, ...]
    """How each backend says "that slug is taken" in an ``IntegrityError``.

    Two spellings because the two dialects report a different thing. Postgres
    names the constraint (``duplicate key value violates unique constraint
    "ix_records_record_type_slug"``); SQLite names the *columns*
    (``UNIQUE constraint failed: records_record.type_id, records_record.locale,
    records_record.slug``) and never mentions the index at all. The column list
    is therefore part of this contract: anything matching neither is re-raised,
    because an ``IntegrityError`` this module cannot explain is a bug rather
    than a 409."""
    group_locale_signatures: tuple[str, ...]
    """The same two spellings for "that language is already taken in this
    group".

    Reached only by a writer that sets ``translation_group`` itself — an import
    carrying the column, or a second ``POST /translations`` that lost the race
    with the first. :func:`sm_records.services._translations.create_translation`
    checks for the sibling first; this is what closes the window behind it, and
    it costs the ordinary write path nothing because the string comparison
    happens only after a flush has already failed."""


def make_record_tables(prefix: str, *, class_suffix: str = "") -> RecordTables:
    """Build the document table and its revision log for one table set.

    ``class_suffix`` keeps the generated classes distinct in SQLAlchemy's
    declarative registry — see :mod:`sm_records.models._factory`.
    """
    record_table = f"{prefix}{RECORD_SUFFIX}"
    revision_table = f"{prefix}{REVISION_SUFFIX}"
    slug_index = f"ix_{record_table}_type_slug"
    group_locale_index = f"ix_{record_table}_group_locale"

    class _Record(AuditMixin, SoftDeleteMixin):
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
        """``records_type`` whichever set this is: the type tables stay global
        (§6.4), and the type row is what *names* the collection."""

        data: dict[str, Any] = Field(
            default_factory=dict,
            sa_column=Column(JSON, nullable=False, default=dict),
        )
        """The payload. History, not the query surface — design §7.2, §8.3."""

        schema_version: int = Field(sa_column_kwargs={"nullable": False})
        """Which ``RecordType.schema_version`` this row was last written against."""

        version: int = Field(default=1, sa_column_kwargs={"nullable": False})
        """Optimistic concurrency. Every write sends the version it read; a
        mismatch is a 409. Design doc §5.1."""

        status: RecordStatus = Field(
            default=RecordStatus.DRAFT,
            sa_column=Column(
                SAEnum(RecordStatus, name=f"{prefix}record_status"),
                nullable=False,
                index=True,
            ),
        )
        """The enum's *type name* is prefixed too. Postgres creates a named type
        per ``sa.Enum``, and two table sets sharing one name would make the
        second ``CREATE TYPE`` a duplicate — the same reason the indexes above
        are named after their table."""

        slug: str | None = Field(default=None, max_length=MAX_SLUG_LEN)
        locale: str = Field(default=DEFAULT_CONTENT_LOCALE, max_length=MAX_LOCALE_LEN)
        """The language this record is written in, **fixed for its lifetime**.

        Every record has one, including on a monolingual install: a nullable
        column would mean every slug lookup had to spell "this locale or
        nothing", and the row that predates the feature would be the one that
        behaves differently. There is no ``locale`` on ``RecordUpdate`` — moving
        a record between languages would strand its slug in the old one, so the
        only way to have the same content in two languages is
        ``POST /records/{uuid}/translations``, which creates a sibling (§4.3).

        The default is the literal ``"en"`` and not the configured
        ``default_content_locale``: this is a column default the ORM applies
        with no request and no ``app.state`` in reach, and the write path
        (``services.records.create_record``) resolves the configured value.
        """

        translation_group: str = Field(
            default_factory=new_uuid, max_length=TRANSLATION_GROUP_LEN, index=True
        )
        """What a record and its translations share.

        A generated key rather than a pointer at "the original", because there
        is no original: translations are siblings, and pointing each at a source
        would make deleting the English record orphan the German one — or
        quietly re-parent it. ``create_record`` sets it to the record's **own
        uuid**, so a record with no siblings is alone in a group named after
        itself; a record created through ``POST /translations`` joins the
        source's group instead. Deleting a record never touches its siblings: a
        group is a grouping, not a cascade.
        """
        display_title: str = Field(default="", max_length=MAX_DISPLAY_TITLE_LEN)
        """Denormalised from ``RecordType.display_field`` on write, recomputed
        by the reindex, so the list screen never parses JSON to render a row."""
        position: int = Field(default=0, sa_column_kwargs={"nullable": False})
        published_at: datetime | None = Field(
            default=None,
            sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
        )

    class _Revision(SQLModel):
        id: int | None = Field(default=None, primary_key=True)
        record_id: int = Field(
            sa_column=Column(ForeignKey(f"{record_table}.id", ondelete="CASCADE"), nullable=False)
        )
        """This set's own record table — a revision never crosses a collection."""
        schema_version: int = Field(sa_column_kwargs={"nullable": False})
        version: int = Field(sa_column_kwargs={"nullable": False})
        """The ``Record.version`` this snapshot *produced*."""
        data: dict[str, Any] = Field(
            default_factory=dict,
            sa_column=Column(JSON, nullable=False, default=dict),
        )
        display_title: str = Field(default="", max_length=MAX_DISPLAY_TITLE_LEN)
        event: RevisionEvent = Field(
            sa_column=Column(SAEnum(RevisionEvent, name=f"{prefix}revision_event"), nullable=False)
        )
        created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
        created_by: str | None = Field(default=None, max_length=255)

    document = table_class(
        f"Record{class_suffix}",
        (Base, _Record),
        tablename=record_table,
        table_args=record_args(record_table, slug_index, group_locale_index),
        doc=_RECORD_DOC,
    )
    # After the class, not inside ``record_args``: these three indexes are
    # declared over the real ``Column`` objects, which ``__table_args__`` does
    # not have (it is evaluated while the table is being built and can only
    # name columns as strings). ``_record_args._DescNullsLast`` says what
    # Alembic does with an index whose columns it cannot find.
    add_descending_indexes(document.__table__)

    return RecordTables(
        record=document,
        revision=table_class(
            f"RecordRevision{class_suffix}",
            (Base, _Revision),
            tablename=revision_table,
            table_args=(Index(f"ix_{revision_table}_record_id", "record_id", "id"),),
            doc=_REVISION_DOC,
        ),
        slug_index=slug_index,
        group_locale_index=group_locale_index,
        slug_signatures=(
            slug_index,
            f"{record_table}.type_id, {record_table}.locale, {record_table}.slug",
        ),
        group_locale_signatures=(
            group_locale_index,
            f"{record_table}.type_id, {record_table}.translation_group, {record_table}.locale",
        ),
    )
