"""How a record list is ordered, and how a cursor resumes it.

Split out of :mod:`sm_records.index.query` for the 300-line cap, along the
seam the ``ORDER BY`` half already had: that module decides *which* field a
name refers to and *whether* it may be asked about, this one turns the answer
into a join, an ordering and — for ``?after=`` — the predicate that resumes it.

Two shapes are load-bearing.

*A single-valued indexed field sorts by a plain ``LEFT OUTER JOIN``.* One
record has at most one row in ``(type_id, field_key, record_id)`` for such a
field, by construction, so the join cannot multiply the result and nothing has
to be aggregated away. The ``GROUP BY record_id`` aggregate this replaced was
correct but paid for a ``MATERIALIZE`` of the whole type, a temp B-tree for the
grouping, an automatic covering index over the materialised rows and a second
temp B-tree for the ordering — all to return 25 rows. ``MIN`` survives for
``multiselect``, a to-many ``relation`` and a provider's ``many`` virtual
field, where a record genuinely holds several values and one of them has to be
chosen; ``MIN`` in both directions, because the value a record sorts by must
not change with the direction.

*``NULLS LAST`` is only worn by columns that can be null.* It is not the order
any btree stores, so a fixed-column sort wearing it is answered with a temp
B-tree over the whole type even when a composite index covers the column
exactly. ``status``, ``position``, ``display_title`` and ``created_at`` are
``NOT NULL`` (``_fixed.NOT_NULL_FIXED_COLUMNS``, read off the mapper), so they
drop it and the index serves the order directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, false, func, nulls_last, or_, select, tuple_
from sqlalchemy.orm import aliased
from sqlalchemy.sql import ColumnElement

from sm_records.index._fields import IndexedField
from sm_records.index._fixed import NOT_NULL_FIXED_COLUMNS, SORT_INDEXED_FIXED_COLUMNS
from sm_records.index._predicates import SORT_ATTR
from sm_records.models import TableSet
from sm_records.schema.types import IndexKind

__all__ = [
    "SortTerm",
    "fixed_term",
    "indexed_term",
    "keyset_clause",
    "ordered",
    "tiebreak_desc",
]


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
    :data:`~sm_records.index._fixed.SORT_INDEXED_FIXED_COLUMNS`. A term
    reached through a join never is: the order comes from the joined row, and
    no index on ``records_record`` knows about it."""


def fixed_term(record: Any, name: str, desc: bool) -> SortTerm:
    """A sort on a column every record has, in the caller's table set."""
    column = getattr(record, name)
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


def tiebreak_desc(terms: Sequence[SortTerm]) -> bool:
    """Which way the ``Record.id`` tiebreaker runs.

    The tiebreaker itself is not optional — without a total order two records
    that tie sort in whatever order the plan happens to produce, and a
    paginated list then shows or skips a row at the page boundary depending on
    the plan; a cursor would be ambiguous for the same reason. Its *direction*
    is free, and there is exactly one case where reversing it pays:

    **a single descending sort on a column a ``(type_id, col, id)`` index
    covers.** ``ORDER BY position DESC, id ASC`` cannot be read off that index
    in either direction, so SQLite walks it backwards and re-sorts every group
    of equal ``position`` — which on the common degenerate case (a type nobody
    has hand-ordered, so every ``position`` is ``0``) is one group holding the
    whole type. ``ORDER BY position DESC, id DESC`` is the same index read
    backwards, start to finish, and stops after ``page_size`` rows.

    **Everywhere else it costs, and badly.** Any other ordering ends in a
    sorter over the whole result. Rows reach that sorter in ``id`` order, so
    an ascending tiebreaker makes every row after the first ``page_size``
    compare worse than the current worst and be dropped on the spot; a
    descending one makes every row better, so each is inserted and one
    evicted — 9,000 insert-and-evict cycles copying whole records, payload
    included. Measured on the list's default ``(position, -updated_at)``
    ordering: **4.1 ms with ``id ASC``, 25.8 ms with ``id DESC``**, same plan
    line, same rows. That is why this is not simply "follow the last term".
    """
    return len(terms) == 1 and terms[0].desc and terms[0].index_served


def ordered(record: Any, stmt: Select, terms: list[SortTerm]) -> Select:
    """Join whatever the terms need and order by them, the record id last."""
    order: list[Any] = []
    for term in terms:
        if term.join is not None:
            stmt = stmt.outerjoin(*term.join)
        direction = term.expr.desc() if term.desc else term.expr.asc()
        order.append(nulls_last(direction) if term.nullable else direction)
    order.append(record.id.desc() if tiebreak_desc(terms) else record.id.asc())
    return stmt.order_by(*order)


def _after(term: SortTerm, value: Any) -> ColumnElement[bool]:
    """Strictly after ``value`` in this term's own order.

    ``NULL`` sorts last, so nothing is after it — ``false()`` rather than a
    predicate, because a comparison against SQL ``NULL`` is unknown and would
    silently drop every remaining row instead of ending the walk.
    """
    if value is None:
        return false()
    beyond = term.expr < value if term.desc else term.expr > value
    return or_(beyond, term.expr.is_(None)) if term.nullable else beyond


def _same(term: SortTerm, value: Any) -> ColumnElement[bool]:
    return term.expr.is_(None) if value is None else term.expr == value


def _row_value_clause(
    record: Any, terms: list[SortTerm], values: list[Any]
) -> ColumnElement[bool] | None:
    """``(col, id) > (:v, :id)`` when that means the same thing, else ``None``.

    A row-value comparison is a **single** comparison the planner can push into
    an index scan, and that is the whole of S3: written as an ``OR`` of three
    comparisons the same predicate lands in the join's ``Filter`` on Postgres,
    after the join, so a deep ``?after=`` page walked every index row for the
    sort field before anything was narrowed. As a row value it seeks —
    ``(type_id, col, id)`` answers it directly, and SQLite reads it off the
    same index (``SEARCH … USING COVERING INDEX … ((col,id)>(?,?))``).

    It is only ever the same thing under four conditions, and each one of them
    is a way the ``OR`` form stayed:

    * **exactly one sort term**, so the tuple is ``(sort value, id)``. Two
      terms could still be expressed, but only if both ran the same way; the
      list's own default ordering (``position``, then ``-updated_at``) does
      not, and an expansion that is right for some multi-term sorts and wrong
      for others is worse than one rule.
    * **the term is not nullable**, i.e. it does not wear ``NULLS LAST``. A row
      value orders by SQL's own rules, where a comparison against ``NULL`` is
      unknown rather than "after everything" — ``NULLS LAST`` is exactly the
      ordering a row value cannot express, and every indexed sort is nullable
      because it is reached by ``LEFT OUTER JOIN``. This is why the measured
      deep-page case (``-placed_at``, an indexed field) keeps the explicit
      form and keeps its plan.
    * **the cursor value is not ``NULL``**, which follows from the above for a
      well-formed cursor and is checked rather than assumed.
    * **the term and the tiebreaker run the same way** (:func:`tiebreak_desc`).
      A descending term that no index serves keeps an *ascending* ``id``, and
      that mixed order is not a row value either.

    Both backends this module claims to run on support row values — Postgres
    always, SQLite since 3.15 (2016) — so there is no dialect to test for here;
    what decides is the shape of the sort, and that is known without a bind.
    """
    if len(terms) != 1:
        return None
    term = terms[0]
    if term.nullable or values[0] is None or tiebreak_desc(terms) != term.desc:
        return None
    left = tuple_(term.expr, record.id)
    right = (values[0], values[-1])
    return left < right if term.desc else left > right


def keyset_clause(record: Any, terms: list[SortTerm], values: list[Any]) -> ColumnElement[bool]:
    """ "Everything the order puts after this row" — design §"F11".

    ``values`` is one per term plus the ``Record.id`` tiebreaker, exactly the
    tuple :mod:`sm_records.index._cursor` decoded.

    A single non-nullable sort term becomes the row-value comparison
    ``(col, id) > (:v, :id)`` — see :func:`_row_value_clause` for when, and why
    that is not every case. Everything else is the lexicographic comparison
    written out, innermost first::

        after(t1) OR (same(t1) AND (after(t2) OR (same(t2) AND id > vid)))

    The ``id`` comparison follows :func:`tiebreak_desc`, exactly as the
    ordering does. The two forms select the same rows in the same order by
    construction — ``tests/test_cursor_keyset.py`` walks a type both ways
    and compares the pages — and the expansion stays for the sorts a row value
    cannot express: several terms, mixed directions, and ``NULLS LAST``.
    """
    row_value = _row_value_clause(record, terms, values)
    if row_value is not None:
        return row_value
    clause: ColumnElement[bool] = (
        record.id < values[-1] if tiebreak_desc(terms) else record.id > values[-1]
    )
    for term, value in zip(reversed(terms), reversed(values[:-1]), strict=True):
        clause = or_(_after(term, value), and_(_same(term, value), clause))
    return clause
