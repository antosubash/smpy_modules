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
from sqlalchemy.orm import aliased

from sm_records.index._cursor import CursorError, decode_cursor, encode_cursor, sort_signature
from sm_records.index._fields import declared_keys, indexed_map
from sm_records.index._filters import Filter, filtered, resolve
from sm_records.index._fixed import FIXED_COLUMNS, fixed_clause
from sm_records.index._predicates import FilterOp, QueryError
from sm_records.index._sorting import SortTerm, fixed_term, indexed_term, keyset_clause, ordered
from sm_records.models import Record, RecordType

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
    "count_query",
    "decode_cursor",
    "encode_cursor",
    "exists_query",
    "fixed_clause",
    "only_trashed",
    "page_query",
    "sort_plan",
    "sort_signature",
    "sort_terms",
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
    """
    terms: list[SortTerm] = []
    for sort in sorts:
        if sort.field in FIXED_COLUMNS:
            terms.append(fixed_term(sort.field, sort.desc))
            continue
        terms.append(
            indexed_term(resolve(rtype, indexed, declared, sort.field), rtype.id, sort.desc)
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
    stmt = filtered(select(Record).where(Record.type_id == rtype.id), rtype, fields, filters)
    return ordered(stmt, sort_terms(rtype, indexed_map(fields), declared_keys(fields), sorts))


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
    stmt = filtered(select(Record).where(Record.type_id == rtype.id), rtype, fields, filters)
    terms = sort_terms(rtype, indexed_map(fields), declared_keys(fields), sorts)
    if after is not None:
        stmt = stmt.where(keyset_clause(terms, after))
    stmt = ordered(stmt, terms)
    return stmt.add_columns(*[term.expr for term in terms]), terms


def only_trashed(stmt: Select) -> Select:
    """Narrow a record query to the trash — the one place that predicate lives.

    Two halves, both needed. ``include_deleted`` lifts the framework's
    soft-delete filter, which is an ORM execute hook this statement never
    mentions (see the module docstring); the explicit ``is_deleted`` is what
    then narrows the result to the deleted rows rather than merging them into
    the live ones. Applied to the count as well as to the page, so a trash
    listing's ``total`` counts what its page shows.
    """
    return stmt.where(Record.is_deleted.is_(True)).execution_options(include_deleted=True)


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
    return filtered(
        select(func.count(Record.id)).where(Record.type_id == rtype.id), rtype, fields, filters
    )


_COUNT_COLUMNS = tuple(
    getattr(Record, column.key) for column in Record.__table__.c if column.name != "data"
)
"""What the bounded count's inner query selects: every column of a record
except the payload.

**Mapped attributes and not ``Record.__table__.c``.** The Core columns compile
to the same SQL and are *not* ORM entity references, so a statement selecting
them names no mapper and the framework's filter skips it — the inner ``LIMIT``
then fills with trashed rows the outer discards, and ``total`` under-counts.
That is a wrong answer rather than a slow one, and
``test_the_bound_does_not_fill_with_trashed_rows`` is what catches it.

Not ``Record.id`` alone, and not ``select(Record)`` either. The outer
aggregate below runs against an ``aliased(Record, <that subquery>)``, so the
framework's soft-delete filter — and any other per-mapper criterion it grows
— is rendered against the *alias*, i.e. against whatever columns the subquery
exposed. Exposing only ``id`` would make a criterion on any other column a
``no such column`` at execute time; exposing all of them would drag ``data``,
the JSON payload (up to ``max_payload_bytes`` each), through a subquery of
10,000 rows. ``data`` is the one column no filter can ever be expressed over
(§7.2), so it is the one that can be left out.
"""


def bounded_count_query(
    rtype: RecordType,
    fields: list[dict[str, Any]],
    filters: Sequence[Filter] = (),
    *,
    cap: int,
    narrow: Any = None,
) -> Select:
    """:func:`count_query`, but it stops counting at ``cap + 1``.

    A page can stop after ``page_size`` matches and the count never could, so
    a filter matching most of a large type paid for all of it on every page of
    it. The inner ``SELECT ... LIMIT cap + 1`` stops as soon as the answer
    "more than ``cap``" is settled; the caller reads ``cap + 1`` as capped and
    reports ``total = cap`` with ``total_capped: true``.

    **The outer aggregate counts an ``aliased(Record, subquery)`` and not a
    bare subquery**, and that is the whole difficulty. The framework's
    soft-delete filter is attached per *mapper found in the statement*, so
    ``select(func.count()).select_from(sub)`` — which names none — counts the
    trash. Naming the entity through an alias over the subquery puts ``Record``
    back in the statement, and the hook then renders its criteria against
    **both** occurrences: inside the subquery, where the ``LIMIT`` needs them
    (otherwise the bound fills with trashed rows the outer discards, and
    ``total`` under-counts near the cap), and against the alias, where it is
    redundant and free.

    The earlier form — ``count(Record.id) WHERE Record.id IN (limited)`` —
    was also correct but read the matching rows *twice*, which measured at
    twice the plain count on a type below the cap. This reads them once.

    ``narrow`` is the caller's own extra predicate on the listing — the trash
    (:func:`only_trashed`) or ``status = published`` — and applies to the
    inner query only: the outer counts exactly the rows the inner produced,
    and a predicate naming ``Record`` out there would name a table the outer
    ``FROM`` does not have. Its execution options are lifted to the outer
    statement, because ``include_deleted`` is read off the statement being
    executed and a nested one is never that.
    """
    apply = narrow if narrow is not None else (lambda stmt: stmt)
    inner = apply(
        filtered(select(*_COUNT_COLUMNS).where(Record.type_id == rtype.id), rtype, fields, filters)
    ).limit(cap + 1)
    counted = aliased(Record, inner.subquery())
    stmt = select(func.count(counted.id)).select_from(counted)
    options = inner.get_execution_options()
    return stmt.execution_options(**options) if options else stmt


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
    stmt = filtered(select(Record.id).where(Record.type_id == rtype.id), rtype, fields, filters)
    return stmt.limit(1)
