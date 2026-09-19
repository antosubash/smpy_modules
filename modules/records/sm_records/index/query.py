"""The filter grammar, compiled to SQL against the index tables.

Design doc §7.2's rule in executable form: **if a field is not indexed, it is
not queryable**. ``Record.data`` is never touched here — no JSON extraction,
no ``LIKE`` over a payload. A field the caller cannot filter by is refused by
name, which makes the cost of a query a property of the schema rather than a
cliff found under load.

Three shapes are load-bearing:

*EXISTS, not JOIN.* A ``multiselect`` has one index row per value. A join
would return the record once per matching row; an EXISTS asks whether any row
matches and returns it once.

*The truncation re-check* of §7.4, in ``_predicates._text_eq``.

*No soft-delete predicate anywhere.* The statement selects the ``Record``
entity, so the framework's ``with_loader_criteria`` hook adds ``is_deleted IS
false`` at execute time — for the same reason index rows carry no record
state. Writing the predicate here as well would be a second copy of a rule
that already has one owner.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, literal, nulls_last, or_, select
from sqlalchemy.sql import ColumnElement

from sm_records.index._coerce import coerce_datetime, coerce_text
from sm_records.index._fields import IndexedField, declared_keys, indexed_map
from sm_records.index._predicates import (
    INDEX_TABLE,
    LIKE_ESCAPE_CHAR,
    SORT_COLUMN,
    FilterOp,
    QueryError,
    like_contains_pattern,
    value_clause,
)
from sm_records.models import Record, RecordStatus, RecordType

__all__ = [
    "FIXED_COLUMNS",
    "Filter",
    "FilterOp",
    "QueryError",
    "Sort",
    "build_query",
    "count_query",
]


@dataclass(frozen=True, slots=True)
class Filter:
    field: str
    op: FilterOp
    value: Any = None


@dataclass(frozen=True, slots=True)
class Sort:
    field: str
    desc: bool = False


FIXED_COLUMNS: frozenset[str] = frozenset(
    {"status", "display_title", "slug", "position", "published_at", "created_at", "updated_at"}
)
"""The projection every record has regardless of its type — the module's
``ContentItemIndex``. Filterable and sortable directly, with no index table
and no ``indexed: true`` anywhere."""

_FIXED_TEXT = frozenset({"display_title", "slug"})
_FIXED_ORDERED = frozenset({"position", "published_at", "created_at", "updated_at"})
_ORDER_OPS = frozenset({FilterOp.GT, FilterOp.GTE, FilterOp.LT, FilterOp.LTE})


def _fixed_value(field: str, value: Any) -> Any:
    if field == "status":
        try:
            return RecordStatus(value)
        except ValueError as exc:
            raise QueryError(field, "bad_value", f"unknown status {value!r}") from exc
    if field == "position":
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise QueryError(field, "bad_value", f"{field!r} takes an integer") from exc
    if field in _FIXED_ORDERED:
        moment: datetime | None = coerce_datetime(value)
        if moment is None:
            raise QueryError(field, "bad_value", f"{field!r} takes an aware datetime")
        return moment
    text = coerce_text(value)
    if text is None:
        raise QueryError(field, "bad_value", f"{field!r} takes a string")
    return text


def _fixed_clause(flt: Filter) -> ColumnElement[bool]:
    """Fixed columns are real columns, so these are ordinary predicates —
    except for ``ne``, which also matches a NULL. SQL's ``<> NULL`` is unknown
    and would drop rows with no slug from a "slug is not 'x'" filter, which is
    not what anybody means by it and disagrees with how ``ne`` reads on an
    index table (absence matches)."""
    column = getattr(Record, flt.field)
    op = flt.op
    if op is FilterOp.IS_NULL:
        return column.is_(None) if flt.value in (None, True) else column.isnot(None)
    if op is FilterOp.CONTAINS:
        if flt.field not in _FIXED_TEXT:
            raise QueryError(flt.field, "unsupported_op", "contains needs a text column")
        pattern = like_contains_pattern(_fixed_value(flt.field, flt.value))
        return column.ilike(pattern, escape=LIKE_ESCAPE_CHAR)
    if op in _ORDER_OPS and flt.field not in _FIXED_ORDERED:
        raise QueryError(flt.field, "unsupported_op", f"{op.value} needs an ordered column")
    if op is FilterOp.IN:
        raw = (
            flt.value if isinstance(flt.value, Sequence) and not isinstance(flt.value, str) else []
        )
        return column.in_([_fixed_value(flt.field, item) for item in raw])
    coerced = _fixed_value(flt.field, flt.value)
    if op is FilterOp.EQ:
        return column == coerced
    if op is FilterOp.NE:
        return or_(column != coerced, column.is_(None))
    return {
        FilterOp.GT: column > coerced,
        FilterOp.GTE: column >= coerced,
        FilterOp.LT: column < coerced,
        FilterOp.LTE: column <= coerced,
    }[op]


def _resolve(rtype: RecordType, indexed: dict[str, IndexedField], declared: set[str], name: str):
    """Which of the three refusals applies, in the order that matters.

    ``reindex_pending`` is checked *first*: mid-move a field's rows exist in
    two tables at once, and whether the definition already says ``indexed``
    depends on where the sequence of §8.5 got to. The temporary answer (409)
    has to win over the permanent one (400), or a caller retries something
    that will never start working.
    """
    if name in (rtype.reindex_pending or []):
        raise QueryError(name, "reindexing", f"{name!r} is being reindexed")
    if name not in declared:
        raise QueryError(name, "unknown", f"{name!r} is not a field of {rtype.key!r}")
    field = indexed.get(name)
    if field is None:
        raise QueryError(name, "not_indexed", f"{name!r} is not indexed, so it is not queryable")
    return field


def _exists(field: IndexedField, type_id: int, clause: ColumnElement[bool] | None):
    table = INDEX_TABLE[field.kind]
    conditions = [
        table.record_id == Record.id,
        table.type_id == type_id,
        table.field_key == field.key,
    ]
    if clause is not None:
        conditions.append(clause)
    return select(literal(1)).select_from(table).where(*conditions).correlate(Record).exists()


def _term(rtype: RecordType, indexed, declared, flt: Filter) -> ColumnElement[bool]:
    if flt.field in FIXED_COLUMNS:
        return _fixed_clause(flt)
    field = _resolve(rtype, indexed, declared, flt.field)
    if flt.op is FilterOp.IS_NULL:
        present = _exists(field, rtype.id, None)
        return ~present if flt.value in (None, True) else present
    clause = value_clause(field.kind, flt.op, flt.value, flt.field)
    term = _exists(field, rtype.id, clause)
    # ``ne`` is the negation of the whole EXISTS: "no value equals x". On a
    # multi-valued field the other reading — "some value differs" — matches a
    # record that also holds x, which nobody asking for ``ne`` wants.
    return ~term if flt.op is FilterOp.NE else term


def _sorted(stmt: Select, rtype: RecordType, indexed, declared, sorts: Iterable[Sort]) -> Select:
    order: list[Any] = []
    for sort in sorts:
        if sort.field in FIXED_COLUMNS:
            column = getattr(Record, sort.field)
            order.append(nulls_last(column.desc() if sort.desc else column.asc()))
            continue
        field = _resolve(rtype, indexed, declared, sort.field)
        table = INDEX_TABLE[field.kind]
        # One row per record by construction, so a multi-valued field orders
        # the result without multiplying it. ``MIN`` in both directions: the
        # value a record sorts by should not change with the direction.
        sub = (
            select(
                table.record_id.label("record_id"),
                func.min(SORT_COLUMN[field.kind]).label("sort_value"),
            )
            .where(table.type_id == rtype.id, table.field_key == field.key)
            .group_by(table.record_id)
            .subquery()
        )
        stmt = stmt.outerjoin(sub, sub.c.record_id == Record.id)
        column = sub.c.sort_value
        order.append(nulls_last(column.desc() if sort.desc else column.asc()))
    # Always last: without a total order, two records that tie sort in
    # whatever order the plan happens to produce, and a paginated list then
    # shows or skips a row at the page boundary depending on the plan.
    order.append(Record.id.asc())
    return stmt.order_by(*order)


def build_query(
    rtype: RecordType,
    fields: list[dict[str, Any]],
    filters: Sequence[Filter] = (),
    sorts: Sequence[Sort] = (),
) -> Select:
    """The record list for one type, filtered and ordered through the index."""
    indexed = indexed_map(fields)
    declared = declared_keys(fields)
    stmt = select(Record).where(Record.type_id == rtype.id)
    for flt in filters:
        stmt = stmt.where(_term(rtype, indexed, declared, flt))
    return _sorted(stmt, rtype, indexed, declared, sorts)


def count_query(
    rtype: RecordType,
    fields: list[dict[str, Any]],
    filters: Sequence[Filter] = (),
    sorts: Sequence[Sort] = (),
) -> Select:
    """How many records ``build_query`` would return.

    ``func.count(Record.id)`` and **not** ``count()`` over ``select_from``:
    the soft-delete filter is attached per *mapper found in the statement's
    columns*, and a bare ``count()`` names no entity — it would count the
    trash. Taking the same ``sorts`` as ``build_query`` and ignoring them
    keeps the two callable with one argument set.
    """
    stmt = select(func.count(Record.id)).where(Record.type_id == rtype.id)
    indexed = indexed_map(fields)
    declared = declared_keys(fields)
    for flt in filters:
        stmt = stmt.where(_term(rtype, indexed, declared, flt))
    return stmt
