"""The index tables — one per value kind, following Orchard Core's
``*FieldIndex`` families over YesSql.

Runtime-defined fields over compile-time tables: the field's identity is
*data* (``type_id``, ``field_key``), not a table name. That is the whole trick
that lets a type created on Tuesday be queryable without a ``CREATE TABLE``.

Index rows carry **no record state** — no ``status``, no ``is_deleted``. Every
query joins to the record table by primary key, and that join is what applies
status, the framework's soft-delete filter, and any future tenant filter. A
mirror would be two copies of two flags to keep in step on every publish, trash
and restore, and every ``COUNT(*)`` would count the trash the moment one copy
lagged. Design doc §7.3.

Rows are derived from ``Record.data`` and are rebuilt by the reindex; a
maintenance bug here yields wrong query results, not slow ones, which is the
genuine cost of this layer and the reason the reindex exists. Design doc §7.7.

**Everything below is a factory.** :func:`make_index_tables` builds one set
against a table prefix, and the global set is one call of it
(:mod:`sm_records.models._tables`). A collection (Phase 5 §6) is another call
with another prefix, so "a collection's index tables are identical in shape to
the global ones" is true by construction rather than by two definitions
agreeing — which is what ``tests/test_collections_ddl.py`` pins.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, Numeric, Text
from sqlmodel import Field, SQLModel

from sm_records.constants import MAX_KEY_LEN, NUMBER_PRECISION, NUMBER_SCALE, TEXT_INDEX_LEN
from sm_records.models._base import (
    INDEX_BOOL_SUFFIX,
    INDEX_DATE_SUFFIX,
    INDEX_DATETIME_SUFFIX,
    INDEX_NUMBER_SUFFIX,
    INDEX_REF_SUFFIX,
    INDEX_TEXT_SUFFIX,
    RECORD_SUFFIX,
    Base,
)
from sm_records.models._factory import table_class
from sm_records.schema.types import IndexKind

INDEX_SUFFIX: dict[IndexKind, str] = {
    IndexKind.TEXT: INDEX_TEXT_SUFFIX,
    IndexKind.NUMBER: INDEX_NUMBER_SUFFIX,
    IndexKind.BOOL: INDEX_BOOL_SUFFIX,
    IndexKind.DATE: INDEX_DATE_SUFFIX,
    IndexKind.DATETIME: INDEX_DATETIME_SUFFIX,
    IndexKind.REF: INDEX_REF_SUFFIX,
}
"""Which table suffix each kind projects into. The one mapping from kind to
physical table, shared by every prefix — a collection's ``text`` rows live in
that collection's ``index_text`` and nowhere else."""


def _record_fk(record_table: str) -> Column:
    # A fresh Column per call: SQLModel shares an ``sa_column`` object across
    # subclasses and SQLAlchemy refuses to assign one Column to two Tables.
    return Column(ForeignKey(f"{record_table}.id", ondelete="CASCADE"), nullable=False)


def _index_args(table: str) -> tuple:
    """The two indexes every kind carries: the filter shape, and the cascade."""
    return (
        Index(f"ix_{table}_lookup", "type_id", "field_key", "value"),
        Index(f"ix_{table}_record", "record_id"),
    )


class _IndexRow(SQLModel):
    """Columns shared by every index kind. Declared with ``sa_type`` /
    ``sa_column_kwargs`` rather than ``sa_column`` so each concrete table gets
    its own ``Column`` objects."""

    id: int | None = Field(default=None, primary_key=True)
    type_id: int = Field(sa_column_kwargs={"nullable": False})
    """Denormalised so a filter never joins just to scope by type.

    It is also what kept collections possible: design §7.3 put it on every
    index row "without a migration of the query layer", and a collection's
    rows carry it for the same reason the global ones do — a collection may
    hold several types."""
    field_key: str = Field(max_length=MAX_KEY_LEN, sa_column_kwargs={"nullable": False})
    """Which field this row indexes — the runtime half of the identity."""


_TEXT_DOC = """``text``, ``select``, ``multiselect``, ``email``, ``url``.

``value`` is the first ``TEXT_INDEX_LEN`` characters and is what the B-tree
covers; ``value_full`` holds the rest only when there is a rest. An equality
filter must match ``value`` *and then re-check* ``value_full`` when it is not
null — two values differing only after the cut are otherwise
indistinguishable. Design doc §7.4."""

_NUMBER_DOC = """``number``, ``integer``.

Five decimal places is the contract; the validator refuses more so payload and
index never disagree. SQLite has no decimal type and stores this as ``REAL`` —
exact on Postgres, approximate on the dev backend."""

_BOOL_DOC = """``boolean``."""

_DATE_DOC = """``date``.

Its own table, not a midnight in the datetime index: a calendar date stored as
a timezone-aware instant matches or misses a ``date =`` filter depending on
the connection's timezone."""

_DATETIME_DOC = """``datetime``, timezone-aware."""

_REF_DOC = """``relation``.

Orchard's ``ContentPickerFieldIndex``: what makes "who references this
record?" a single indexed query, so ``restrict`` on delete is a lookup rather
than a scan. Design doc §9. The lookup index is on ``target_uuid`` rather than
``value`` — the question this table answers most is "who points at X", not
"what does field F of type T point at".

A ref row lives in the **referrer's** table set and names its target by
``(target_uuid, target_type_id)``, which is what makes a relation across
collections expressible at all — and why "who references X" has to ask every
declared set rather than one
(:func:`sm_records.services._relations.referrers`)."""


def _ref_args(table: str) -> tuple:
    """The reference index's own three, which are not ``_index_args``: there
    is no ``value`` column to cover, and ``target_uuid`` leads instead."""
    return (
        Index(f"ix_{table}_target", "target_uuid"),
        Index(f"ix_{table}_lookup", "type_id", "field_key", "target_uuid"),
        Index(f"ix_{table}_record", "record_id"),
    )


def make_index_tables(prefix: str, *, class_suffix: str = "") -> dict[IndexKind, type]:
    """Build the six index tables for one table set. See the module docstring.

    ``class_suffix`` distinguishes the generated classes in SQLAlchemy's
    declarative registry, which is keyed by class name — see
    :mod:`sm_records.models._factory`. It is cosmetic to the database and
    load-bearing to the mapper.
    """
    record_table = f"{prefix}{RECORD_SUFFIX}"
    names = {kind: f"{prefix}{suffix}" for kind, suffix in INDEX_SUFFIX.items()}

    class _Text(_IndexRow):
        record_id: int = Field(sa_column=_record_fk(record_table))
        value: str = Field(max_length=TEXT_INDEX_LEN, sa_column_kwargs={"nullable": False})
        value_full: str | None = Field(default=None, sa_type=Text)

    class _Number(_IndexRow):
        record_id: int = Field(sa_column=_record_fk(record_table))
        value: Decimal = Field(
            sa_type=Numeric(NUMBER_PRECISION, NUMBER_SCALE),
            sa_column_kwargs={"nullable": False},
        )

    class _Bool(_IndexRow):
        record_id: int = Field(sa_column=_record_fk(record_table))
        value: bool = Field(sa_type=Boolean, sa_column_kwargs={"nullable": False})

    class _Date(_IndexRow):
        record_id: int = Field(sa_column=_record_fk(record_table))
        value: date = Field(sa_type=Date, sa_column_kwargs={"nullable": False})

    class _Datetime(_IndexRow):
        record_id: int = Field(sa_column=_record_fk(record_table))
        value: datetime = Field(
            sa_type=DateTime(timezone=True), sa_column_kwargs={"nullable": False}
        )

    class _Ref(_IndexRow):
        record_id: int = Field(sa_column=_record_fk(record_table))
        target_uuid: str = Field(max_length=32, sa_column_kwargs={"nullable": False})
        target_type_id: int = Field(sa_column_kwargs={"nullable": False})

    def build(kind: IndexKind, stem: str, shape: type, doc: str) -> type:
        table = names[kind]
        args = _ref_args(table) if kind is IndexKind.REF else _index_args(table)
        return table_class(
            f"{stem}{class_suffix}",
            (Base, shape),
            tablename=table,
            table_args=args,
            doc=doc,
        )

    return {
        IndexKind.TEXT: build(IndexKind.TEXT, "IndexText", _Text, _TEXT_DOC),
        IndexKind.NUMBER: build(IndexKind.NUMBER, "IndexNumber", _Number, _NUMBER_DOC),
        IndexKind.BOOL: build(IndexKind.BOOL, "IndexBool", _Bool, _BOOL_DOC),
        IndexKind.DATE: build(IndexKind.DATE, "IndexDate", _Date, _DATE_DOC),
        IndexKind.DATETIME: build(IndexKind.DATETIME, "IndexDatetime", _Datetime, _DATETIME_DOC),
        IndexKind.REF: build(IndexKind.REF, "IndexRef", _Ref, _REF_DOC),
    }
