"""index _sort_terms helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql import ColumnElement

from sm_records.models import TableSet
from sm_records.records.index._fields import IndexedField
from sm_records.records.index._fixed import (
    NOT_NULL_FIXED_COLUMNS,
    SORT_INDEXED_FIXED_COLUMNS,
    fixed_column,
)
from sm_records.records.index._predicates import SORT_ATTR
from sm_records.schema.types import IndexKind


@dataclass(frozen=True, slots=True)
class SortTerm:
    """One ``ORDER BY`` element, with everything a cursor needs about it."""

    expr: Any
    """The SQL expression to order by *and* to compare a cursor value against
    — the same object, so a keyset predicate can never drift from the order it
    is resuming."""
    desc: bool
    nullable: bool
    """Whether the expression can be ``NULL``, i.e. whether it wears
    ``NULLS LAST``. A ``LEFT OUTER JOIN`` makes every indexed sort nullable
    whatever the index column says: a record with no row for the field joins
    to nothing."""
    kind: IndexKind | None
    """The index kind behind the expression, or ``None`` for a fixed column —
    which of the two decides how a cursor value is decoded."""
    fixed: str | None
    """The fixed column's name, when this is one."""
    join: tuple[Any, ColumnElement[bool]] | None
    """``(selectable, onclause)`` to ``LEFT OUTER JOIN``, or ``None`` for a
    fixed column, which needs no join at all."""
    index_served: bool = False
    """Whether a ``(type_id, <this column>, id)`` index can produce this
    term's order directly — true only for the fixed columns of
    :data:`~sm_records.records.index._fixed.SORT_INDEXED_FIXED_COLUMNS`. A term
    reached through a join never is: the order comes from the joined row, and
    no index on ``records_record`` knows about it."""


def fixed_term(record: Any, name: str, desc: bool) -> SortTerm:
    """A sort on a column every record has, in the caller's table set.

    ``fixed_column`` and not ``getattr``: ``invalid`` is a grammar name for
    the ``invalid_since`` column (``_fixed._FIXED_ALIAS``), and this orders by
    the timestamp — which puts the marked records first, oldest mark first,
    and the rest behind them under ``NULLS LAST``.
    """
    column = fixed_column(record, name)
    return SortTerm(
        expr=column,
        desc=desc,
        nullable=name not in NOT_NULL_FIXED_COLUMNS,
        kind=None,
        fixed=name,
        join=None,
        index_served=name in SORT_INDEXED_FIXED_COLUMNS,
    )


def indexed_term(tables: TableSet, field: IndexedField, type_id: int, desc: bool) -> SortTerm:
    """A sort on an indexed field, joined out of ``tables``'s own index table.

    Both halves of the join belong to one table set: a record's index rows live
    beside it, so an ordering never crosses a collection (Phase 5 §6.3).
    """
    record = tables.record
    table = tables.index[field.kind]
    attr = SORT_ATTR[field.kind]
    if field.many:
        sub = (
            select(
                table.record_id.label("record_id"),
                func.min(getattr(table, attr)).label("sort_value"),
            )
            .where(table.type_id == type_id, table.field_key == field.key)
            .group_by(table.record_id)
            .subquery()
        )
        return SortTerm(
            expr=sub.c.sort_value,
            desc=desc,
            nullable=True,
            kind=field.kind,
            fixed=None,
            join=(sub, sub.c.record_id == record.id),
        )
    alias = aliased(table)
    # ``record_id`` and ``field_key``, and deliberately **not** ``type_id``.
    # A record belongs to one type, so the denormalised ``type_id`` on the
    # index row is implied by ``record_id`` and adds nothing to the predicate
    # — but it adds a great deal to the planner's guess. Given
    # ``type_id = ? AND field_key = ?`` SQLite scores the two-equality
    # ``(type_id, field_key, value)`` lookup index above the single-equality
    # ``(record_id)`` one, and then re-scans the whole (type, field) range of
    # the index once per record of the type: sorting 9,000 orders by
    # ``customer`` took **42 seconds** that way. With ``type_id`` out of the
    # clause no lookup index has a usable leading column left, the
    # ``record_id`` index is the only candidate, and the join is a point
    # lookup per row again. Design §7.3's "denormalised so a query never
    # joins to filter by type" is about the *filter* semi-join, which still
    # uses all three.
    onclause = and_(alias.record_id == record.id, alias.field_key == field.key)
    return SortTerm(
        expr=getattr(alias, attr),
        desc=desc,
        nullable=True,
        kind=field.kind,
        fixed=None,
        join=(alias, onclause),
    )
