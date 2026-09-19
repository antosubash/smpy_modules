"""The filter grammar, compiled to SQL against the index tables.

Design doc §7.2's rule in executable form: **if a field is not indexed, it is
not queryable**. ``Record.data`` is never touched here — no JSON extraction,
no ``LIKE`` over a payload. A field the caller cannot filter by is refused by
name, which makes the cost of a query a property of the schema rather than a
cliff found under load.

Three shapes are load-bearing:

*A semi-join, not a JOIN and not a correlated EXISTS.* A ``multiselect`` has
one index row per value, so an inner join would return the record once per
matching row; ``Record.id IN (SELECT record_id FROM idx WHERE …)`` asks whether
any row matches and returns the record once, because ``IN`` deduplicates. It is
not the correlated ``EXISTS`` it replaced either: that form made the subquery a
function of the outer row, so its cost was (records of the type) x (work per
probe) and SQLite — given two usable indexes and no ``sqlite_stat1`` — regularly
picked the value index and then filtered its whole matching range by
``record_id`` once per record of the type. The semi-join runs once, from the
index rows that match, and is therefore proportional to *what matches* rather
than to how big the type is, on every backend and with or without statistics.

*The truncation re-check* of §7.4, in ``_predicates._text_eq``.

*The fixed columns are somebody else's job.* ``status``, ``slug`` and the
rest of §7.2's projection are real columns and need none of this machinery;
they live in :mod:`sm_records.index._fixed`.

*No soft-delete predicate anywhere.* The statement selects the ``Record``
entity, so the framework's ``with_loader_criteria`` hook adds ``is_deleted IS
false`` at execute time — for the same reason index rows carry no record
state. Writing the predicate here as well would be a second copy of a rule
that already has one owner.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, nulls_last, select
from sqlalchemy.sql import ColumnElement

from sm_records.index._fields import IndexedField, declared_keys, indexed_map
from sm_records.index._fixed import FIXED_COLUMNS, fixed_clause
from sm_records.index._predicates import (
    INDEX_TABLE,
    SORT_COLUMN,
    FilterOp,
    QueryError,
    value_clause,
)
from sm_records.models import Record, RecordType

__all__ = [
    "FIXED_COLUMNS",
    "Filter",
    "FilterOp",
    "QueryError",
    "Sort",
    "build_query",
    "count_query",
    "exists_query",
    "only_trashed",
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


def _resolve(rtype: RecordType, indexed: dict[str, IndexedField], declared: set[str], name: str):
    """Which of the three refusals applies, in the order that matters.

    ``reindex_pending`` is checked *first*: mid-move a field's rows exist in
    two tables at once, and whether the definition already says ``indexed``
    depends on where the sequence of §8.5 got to. The temporary answer (409)
    has to win over the permanent one (400), or a caller retries something
    that will never start working.

    ``reindex_pending`` is a mapping of key → enqueued-at, so membership is a
    key test. Its reserved ``"*"`` entry (a whole-type ``display_title``
    rebuild) is unreachable here: no field key can be ``*``.
    """
    if name in (rtype.reindex_pending or {}):
        raise QueryError(name, "reindexing", f"{name!r} is being reindexed")
    if name not in declared:
        raise QueryError(name, "unknown", f"{name!r} is not a field of {rtype.key!r}")
    field = indexed.get(name)
    if field is None:
        raise QueryError(name, "not_indexed", f"{name!r} is not indexed, so it is not queryable")
    return field


def _holders(field: IndexedField, type_id: int, clause: ColumnElement[bool] | None) -> Select:
    """The ids of the records holding an index row that matches.

    Uncorrelated on purpose — see the module docstring. ``record_id`` is
    ``NOT NULL`` on every index table, which is what makes the negated form
    (``NOT IN``) safe: a NULL anywhere in this result would make ``NOT IN``
    unknown for every row and silently empty the page.
    """
    table = INDEX_TABLE[field.kind]
    conditions = [table.type_id == type_id, table.field_key == field.key]
    if clause is not None:
        conditions.append(clause)
    return select(table.record_id).where(*conditions)


def _term(rtype: RecordType, indexed, declared, flt: Filter) -> ColumnElement[bool]:
    if flt.field in FIXED_COLUMNS:
        return fixed_clause(flt.field, flt.op, flt.value)
    field = _resolve(rtype, indexed, declared, flt.field)
    if flt.op is FilterOp.IS_NULL:
        holders = _holders(field, rtype.id, None)
        # "has no value" is the absence of any row, so it is the negation of
        # the whole semi-join — not a predicate over one row.
        return Record.id.not_in(holders) if flt.value in (None, True) else Record.id.in_(holders)
    clause = value_clause(field.kind, flt.op, flt.value, flt.field)
    holders = _holders(field, rtype.id, clause)
    # ``ne`` negates the whole semi-join: "no value equals x". On a
    # multi-valued field the other reading — "some value differs" — matches a
    # record that also holds x, which nobody asking for ``ne`` wants. ``eq``
    # on the same field is the ``any`` reading, which ``IN`` gives directly.
    return Record.id.not_in(holders) if flt.op is FilterOp.NE else Record.id.in_(holders)


def _filtered(stmt: Select, rtype: RecordType, fields: list[dict[str, Any]], filters) -> Select:
    """Apply every filter to ``stmt`` — the one place a term is built, so the
    page, its total and the ``unique`` check of §7.8 cannot drift apart."""
    indexed = indexed_map(fields)
    declared = declared_keys(fields)
    for flt in filters:
        stmt = stmt.where(_term(rtype, indexed, declared, flt))
    return stmt


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
    stmt = _filtered(select(Record).where(Record.type_id == rtype.id), rtype, fields, filters)
    return _sorted(stmt, rtype, indexed_map(fields), declared_keys(fields), sorts)


def only_trashed(stmt: Select) -> Select:
    """Narrow a record query to the trash — the one place that predicate lives.

    Two halves, both needed. ``include_deleted`` lifts the framework's
    soft-delete filter, which is an ORM execute hook this statement never
    mentions (see the module docstring); the explicit ``is_deleted`` is what
    then narrows the result to the deleted rows rather than merging them into
    the live ones. Applied to ``count_query`` as well as ``build_query``, so a
    trash listing's ``total`` counts what its page shows.
    """
    return stmt.where(Record.is_deleted.is_(True)).execution_options(include_deleted=True)


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
    return _filtered(
        select(func.count(Record.id)).where(Record.type_id == rtype.id), rtype, fields, filters
    )


def exists_query(
    rtype: RecordType,
    fields: list[dict[str, Any]],
    filters: Sequence[Filter] = (),
) -> Select:
    """Whether ``build_query`` would return **anything** — the same question as
    ``count_query`` without the unbounded aggregate.

    Every term is built by the same :func:`_term`, so the §7.4 truncation
    re-check and the refusals of :func:`_resolve` are shared with the filter
    grammar rather than copied. The difference is only the projection and the
    ``LIMIT 1``: a caller asking "is this value taken" made the database count
    every record of the type to learn a fact one row settles, which is what
    made a write to a type with a ``unique`` field O(rows in that type).

    ``select(Record.id)`` and not ``select(literal(1))``: naming the mapper is
    what the framework's soft-delete filter attaches to (see
    :func:`count_query`), and a caller that wants the trash included — the
    ``unique`` check does — lifts it with ``include_deleted`` as usual.
    """
    stmt = _filtered(select(Record.id).where(Record.type_id == rtype.id), rtype, fields, filters)
    return stmt.limit(1)
