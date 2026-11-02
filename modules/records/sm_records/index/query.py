"""The filter and sort grammar, compiled to SQL against the index tables.

Design doc §7.2's rule in executable form: **if a field is not indexed, it is
not queryable**. ``Record.data`` is never touched here — no JSON extraction,
no ``LIKE`` over a payload. A field the caller cannot filter by is refused by
name, which makes the cost of a query a property of the schema rather than a
cliff found under load.

This module is the façade and the arithmetic of a page. The three halves it
assembles live beside it, each under the file cap and each readable alone:
:mod:`sm_records.index._filters` (which records match, and the semi-join that
is the whole of F1), :mod:`sm_records.index._sorting` (in what order, and the
joins that produce it) and :mod:`sm_records.index._cursor` (how a caller says
"resume after this row"). ``_fixed`` owns the columns every record has
whatever its type declares, and ``_predicates`` the per-kind value SQL.

*No soft-delete predicate anywhere.* Every statement below selects the
``Record`` entity, so the framework's ``with_loader_criteria`` hook adds
``is_deleted IS false`` at execute time — for the same reason index rows carry
no record state. Writing the predicate here as well would be a second copy of
a rule that already has one owner, and the one place it is *lifted*
(:func:`only_trashed`) says so out loud.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, select

from sm_records.index._bounded import bounded_count_query, count_columns
from sm_records.index._cursor import CursorError, decode_cursor, encode_cursor, sort_signature
from sm_records.index._fields import declared_keys, indexed_map
from sm_records.index._filters import Filter, filtered, resolve
from sm_records.index._fixed import FIXED_COLUMNS
from sm_records.index._predicates import FilterOp, QueryError
from sm_records.index._sorting import SortTerm, fixed_term, indexed_term, keyset_clause, ordered
from sm_records.models import RecordType, tables_for

__all__ = [
    "FIXED_COLUMNS",
    "CursorError",
    "Filter",
    "FilterOp",
    "QueryError",
    "Sort",
    "SortTerm",
    "bounded_count_query",
    "build_query",
    "count_columns",
    "count_query",
    "decode_cursor",
    "encode_cursor",
    "exists_query",
    "filtered",
    "only_trashed",
    "page_query",
    "sort_plan",
    "sort_signature",
    "sort_terms",
    "tables_for",
]


@dataclass(frozen=True, slots=True)
class Sort:
    field: str
    desc: bool = False


def sort_terms(rtype: RecordType, indexed, declared, sorts: Iterable[Sort]) -> list[SortTerm]:
    """Resolve each requested sort to a :class:`~sm_records.index._sorting.SortTerm`.

    The refusals are :func:`sm_records.index._filters.resolve`'s, unchanged —
    a sort on a field that is mid-reindex is the same 409 a filter on it is,
    and one on an unindexed field the same 400. What a term *is* once
    resolved, and what it costs, is ``_sorting``'s subject.

    The table set comes from ``rtype`` (Phase 5 §6.3), so a sort on a
    collection type joins that collection's index tables.
    """
    tables = tables_for(rtype)
    terms: list[SortTerm] = []
    for sort in sorts:
        if sort.field in FIXED_COLUMNS:
            terms.append(fixed_term(tables.record, sort.field, sort.desc))
            continue
        terms.append(
            indexed_term(tables, resolve(rtype, indexed, declared, sort.field), rtype.id, sort.desc)
        )
    return terms


def sort_plan(
    rtype: RecordType, fields: list[dict[str, Any]], sorts: Sequence[Sort] = ()
) -> list[SortTerm]:
    """:func:`sort_terms` from a raw ``fields`` list — what a caller needs to
    *decode* a cursor, before it has a statement to run."""
    return sort_terms(rtype, indexed_map(fields), declared_keys(fields), sorts)


def build_query(
    rtype: RecordType,
    fields: list[dict[str, Any]],
    filters: Sequence[Filter] = (),
    sorts: Sequence[Sort] = (),
) -> Select:
    """The record list for one type, filtered and ordered through the index."""
    record = tables_for(rtype).record
    stmt = filtered(select(record).where(record.type_id == rtype.id), rtype, fields, filters)
    return ordered(record, stmt, sort_plan(rtype, fields, sorts))


def page_query(
    rtype: RecordType,
    fields: list[dict[str, Any]],
    filters: Sequence[Filter] = (),
    sorts: Sequence[Sort] = (),
    *,
    after: list[Any] | None = None,
) -> tuple[Select, list[SortTerm]]:
    """:func:`build_query`, plus the sort values of every row it returns.

    The extra columns are what makes a cursor possible at all: the ordering
    may be an expression on a joined index row, which the ``Record`` entity
    does not carry, so a caller that wants to say "resume after this row" has
    to be handed the values the order actually used. Rows come back as
    ``(Record, *sort values)``.

    ``after`` is the decoded cursor tuple (:mod:`sm_records.index._cursor`);
    it narrows the statement to what the order puts strictly after that row,
    with no ``OFFSET`` anywhere.
    """
    record = tables_for(rtype).record
    stmt = filtered(select(record).where(record.type_id == rtype.id), rtype, fields, filters)
    terms = sort_plan(rtype, fields, sorts)
    if after is not None:
        stmt = stmt.where(keyset_clause(record, terms, after))
    stmt = ordered(record, stmt, terms)
    return stmt.add_columns(*[term.expr for term in terms]), terms


def only_trashed(record: Any, stmt: Select) -> Select:
    """Narrow a record query to the trash — the one place that predicate lives.

    Two halves, both needed. ``include_deleted`` lifts the framework's
    soft-delete filter, which is an ORM execute hook this statement never
    mentions (see the module docstring); the explicit ``is_deleted`` is what
    then narrows the result to the deleted rows rather than merging them into
    the live ones. Applied to the count as well as to the page, so a trash
    listing's ``total`` counts what its page shows.
    """
    return stmt.where(record.is_deleted.is_(True)).execution_options(include_deleted=True)


def count_query(
    rtype: RecordType,
    fields: list[dict[str, Any]],
    filters: Sequence[Filter] = (),
    sorts: Sequence[Sort] = (),
) -> Select:
    """How many records ``build_query`` would return, exactly and unbounded.

    ``func.count(Record.id)`` and **not** ``count()`` over ``select_from``:
    the soft-delete filter is attached per *mapper found in the statement's
    columns*, and a bare ``count()`` names no entity — it would count the
    trash. Taking the same ``sorts`` as ``build_query`` and ignoring them
    keeps the two callable with one argument set.

    The list endpoints use :func:`bounded_count_query` instead; this stays for
    the callers that genuinely want the whole number and know the type is
    small — and as the thing the bounded form is defined against.
    """
    record = tables_for(rtype).record
    return filtered(
        select(func.count(record.id)).where(record.type_id == rtype.id), rtype, fields, filters
    )


def exists_query(
    rtype: RecordType,
    fields: list[dict[str, Any]],
    filters: Sequence[Filter] = (),
) -> Select:
    """Whether ``build_query`` would return **anything** — the same question as
    ``count_query`` without the unbounded aggregate.

    Every term is built by the same builder, so the §7.4 truncation re-check
    and the refusals of :func:`sm_records.index._filters.resolve` are shared
    with the filter grammar rather than copied. The difference is only the
    projection and the ``LIMIT 1``: a caller asking "is this value taken" made
    the database count every record of the type to learn a fact one row
    settles, which is what made a write to a type with a ``unique`` field
    O(rows in that type).

    ``select(Record.id)`` and not ``select(literal(1))``: naming the mapper is
    what the framework's soft-delete filter attaches to (see
    :func:`count_query`), and a caller that wants the trash included — the
    ``unique`` check does — lifts it with ``include_deleted`` as usual.
    """
    record = tables_for(rtype).record
    stmt = filtered(select(record.id).where(record.type_id == rtype.id), rtype, fields, filters)
    return stmt.limit(1)
