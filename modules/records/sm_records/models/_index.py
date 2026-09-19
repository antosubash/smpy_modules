"""The index tables — one per value kind, following Orchard Core's
``*FieldIndex`` families over YesSql.

Runtime-defined fields over compile-time tables: the field's identity is
*data* (``type_id``, ``field_key``), not a table name. That is the whole trick
that lets a type created on Tuesday be queryable without a ``CREATE TABLE``.

Index rows carry **no record state** — no ``status``, no ``is_deleted``. Every
query joins to ``records_record`` by primary key, and that join is what
applies status, the framework's soft-delete filter, and any future tenant
filter. A mirror would be two copies of two flags to keep in step on every
publish, trash and restore, and every ``COUNT(*)`` would count the trash the
moment one copy lagged. Design doc §7.3.

Rows are derived from ``Record.data`` and are rebuilt by the reindex; a
maintenance bug here yields wrong query results, not slow ones, which is the
genuine cost of this layer and the reason the reindex exists. Design doc §7.7.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, Numeric, Text
from sqlmodel import Field, SQLModel

from sm_records.constants import MAX_KEY_LEN, NUMBER_PRECISION, NUMBER_SCALE, TEXT_INDEX_LEN
from sm_records.models._base import (
    INDEX_BOOL_TABLE,
    INDEX_DATE_TABLE,
    INDEX_DATETIME_TABLE,
    INDEX_NUMBER_TABLE,
    INDEX_REF_TABLE,
    INDEX_TEXT_TABLE,
    RECORD_TABLE,
    Base,
)


def _record_fk() -> Column:
    # A fresh Column per call: SQLModel shares an ``sa_column`` object across
    # subclasses and SQLAlchemy refuses to assign one Column to two Tables.
    return Column(ForeignKey(f"{RECORD_TABLE}.id", ondelete="CASCADE"), nullable=False)


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
    """Denormalised so a filter never joins just to scope by type."""
    field_key: str = Field(max_length=MAX_KEY_LEN, sa_column_kwargs={"nullable": False})
    """Which field this row indexes — the runtime half of the identity."""


class IndexText(Base, _IndexRow, table=True):  # ty: ignore[unsupported-base]
    """``text``, ``select``, ``multiselect``, ``email``, ``url``.

    ``value`` is the first ``TEXT_INDEX_LEN`` characters and is what the
    B-tree covers; ``value_full`` holds the rest only when there is a rest.
    An equality filter must match ``value`` *and then re-check* ``value_full``
    when it is not null — two values differing only after the cut are
    otherwise indistinguishable. Design doc §7.4.
    """

    __tablename__ = INDEX_TEXT_TABLE
    __table_args__ = _index_args(INDEX_TEXT_TABLE)

    record_id: int = Field(sa_column=_record_fk())
    value: str = Field(max_length=TEXT_INDEX_LEN, sa_column_kwargs={"nullable": False})
    value_full: str | None = Field(default=None, sa_type=Text)


class IndexNumber(Base, _IndexRow, table=True):  # ty: ignore[unsupported-base]
    """``number``, ``integer``. Five decimal places is the contract; the
    validator refuses more so payload and index never disagree. SQLite has no
    decimal type and stores this as ``REAL`` — exact on Postgres, approximate
    on the dev backend."""

    __tablename__ = INDEX_NUMBER_TABLE
    __table_args__ = _index_args(INDEX_NUMBER_TABLE)

    record_id: int = Field(sa_column=_record_fk())
    value: Decimal = Field(
        sa_type=Numeric(NUMBER_PRECISION, NUMBER_SCALE),
        sa_column_kwargs={"nullable": False},
    )


class IndexBool(Base, _IndexRow, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = INDEX_BOOL_TABLE
    __table_args__ = _index_args(INDEX_BOOL_TABLE)

    record_id: int = Field(sa_column=_record_fk())
    value: bool = Field(sa_type=Boolean, sa_column_kwargs={"nullable": False})


class IndexDate(Base, _IndexRow, table=True):  # ty: ignore[unsupported-base]
    """``date``. Its own table, not a midnight in ``IndexDatetime``: a calendar
    date stored as a timezone-aware instant matches or misses a ``date =``
    filter depending on the connection's timezone."""

    __tablename__ = INDEX_DATE_TABLE
    __table_args__ = _index_args(INDEX_DATE_TABLE)

    record_id: int = Field(sa_column=_record_fk())
    value: date = Field(sa_type=Date, sa_column_kwargs={"nullable": False})


class IndexDatetime(Base, _IndexRow, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = INDEX_DATETIME_TABLE
    __table_args__ = _index_args(INDEX_DATETIME_TABLE)

    record_id: int = Field(sa_column=_record_fk())
    value: datetime = Field(sa_type=DateTime(timezone=True), sa_column_kwargs={"nullable": False})


class IndexRef(Base, _IndexRow, table=True):  # ty: ignore[unsupported-base]
    """``relation``. Orchard's ``ContentPickerFieldIndex``: what makes "who
    references this record?" a single indexed query, so ``restrict`` on delete
    is a lookup rather than a scan. Design doc §9.

    The lookup index is on ``target_uuid`` rather than ``value`` — the
    question this table answers most is "who points at X", not "what does
    field F of type T point at"."""

    __tablename__ = INDEX_REF_TABLE
    __table_args__ = (
        Index(f"ix_{INDEX_REF_TABLE}_target", "target_uuid"),
        Index(f"ix_{INDEX_REF_TABLE}_lookup", "type_id", "field_key", "target_uuid"),
        Index(f"ix_{INDEX_REF_TABLE}_record", "record_id"),
    )

    record_id: int = Field(sa_column=_record_fk())
    target_uuid: str = Field(max_length=32, sa_column_kwargs={"nullable": False})
    target_type_id: int = Field(sa_column_kwargs={"nullable": False})
