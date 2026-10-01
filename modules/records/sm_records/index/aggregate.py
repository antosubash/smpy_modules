"""``GROUP BY`` over the map indexes — the live aggregate of Phase 5 §5.1.

The original design (§7.5) refused a maintained aggregate on the grounds that
the aggregates this module actually needs are "``COUNT(*)`` with a ``GROUP BY``
against an indexed table". This module is that sentence, compiled.

Two things it shares with the list query, on purpose, because a dashboard that
counts a different set from the one the list shows is worse than no dashboard:

* **The same filter terms.** ``_filters.filtered`` is applied unchanged, so
  the semi-join, the §7.4 truncation re-check and the three refusals
  (``unknown`` 400, ``not_indexed`` 400, ``reindexing`` 409) are the filter
  grammar's, not a second copy of them. ``group_by`` is resolved through the
  *same* :func:`sm_records.index._filters.resolve`, so grouping by a field
  that is mid-rebuild is the 409 filtering by it is.
* **The same soft-delete rule.** Every statement here names the document
  mapper — ``select_from(record)`` and ``count(distinct(record.id))`` — which
  is what the framework's ``with_loader_criteria`` hook attaches
  ``is_deleted IS false`` to. A bare ``select(func.count())`` names none and
  counts the trash; that is F4's trap in ``docs/performance.md``, and it
  applies here word for word.

**A multi-valued ``group_by`` counts a record once per value.** A record with
``tags = ["a", "b"]`` appears in both groups, so the group counts sum to more
than the number of records — which is the only honest reading of "records per
tag" and the same reading ``filter=tags:eq:a`` has.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, desc, distinct, func, select
from sqlalchemy.orm import aliased

from sm_records.index._fields import declared_keys, indexed_map
from sm_records.index._filters import filtered, resolve
from sm_records.index._fixed import FIXED_COLUMNS, fixed_expression
from sm_records.index._predicates import SORT_ATTR, QueryError
from sm_records.models import TableSet, tables_for
from sm_records.schema.types import IndexKind

__all__ = ["Metric", "aggregate_query", "parse_metric"]

FIXED_KIND: dict[str, IndexKind] = {
    "status": IndexKind.TEXT,
    "display_title": IndexKind.TEXT,
    "slug": IndexKind.TEXT,
    "locale": IndexKind.TEXT,
    "position": IndexKind.NUMBER,
    "published_at": IndexKind.DATETIME,
    "created_at": IndexKind.DATETIME,
    "updated_at": IndexKind.DATETIME,
    # A boolean, although the column behind it is a timestamp: grouping by
    # ``invalid`` has to give two groups rather than one per instant a record
    # was marked, which is what ``_fixed.fixed_expression`` renders. BOOL is
    # in neither ``SUM_KINDS`` nor ``ORDER_KINDS``, so ``count`` is the only
    # metric it can carry — the only one that means anything over a flag.
    "invalid": IndexKind.BOOL,
}
"""What kind of value each fixed column holds, for the metric rules below.
Listed rather than derived because it answers a question about *meaning* —
``status`` is an enum the database stores as text — and the derived
alternatives (``NOT_NULL_FIXED_COLUMNS``) answer questions about the column."""

SUM_KINDS = frozenset({IndexKind.NUMBER})
"""``sum`` folds numbers and nothing else. Adding dates together is not an
operation, and concatenating text is not what anybody means by it."""

ORDER_KINDS = frozenset({IndexKind.NUMBER, IndexKind.DATE, IndexKind.DATETIME, IndexKind.TEXT})
"""``min``/``max`` need an order. ``bool`` has one and it is useless; a
``relation`` is indexed by uuid, whose order means nothing at all."""


@dataclass(frozen=True, slots=True)
class Metric:
    """``count``, or one of ``sum``/``min``/``max`` over a named field."""

    op: str
    field: str | None = None

    def __str__(self) -> str:
        return self.op if self.field is None else f"{self.op}:{self.field}"


_OPS = frozenset({"count", "sum", "min", "max"})


def parse_metric(raw: str | None) -> Metric:
    """``count`` | ``sum:<field>`` | ``min:<field>`` | ``max:<field>``.

    A :class:`~sm_records.index._predicates.QueryError` and not an
    ``HTTPException``, so the aggregate endpoint refuses a bad metric through
    exactly the route wrapper that refuses a bad filter — one shape of error
    body for one shape of mistake.
    """
    if not raw:
        return Metric("count")
    op, _, field = raw.partition(":")
    if op not in _OPS:
        raise QueryError(
            "metric",
            "bad_value",
            f"unknown metric {op!r}: expected one of {', '.join(sorted(_OPS))}",
        )
    if op == "count":
        return Metric("count")
    if not field:
        raise QueryError("metric", "bad_value", f"{op!r} needs a field: '{op}:<field>'")
    return Metric(op, field)


def _column(
    tables: TableSet, rtype, indexed, declared, name: str
) -> tuple[Any, IndexKind, Any, bool]:
    """``(expression, kind, index table or None, multi-valued)`` for one name.

    A fixed column is a real column on the document table and needs no join;
    anything else is resolved through the filter grammar and read out of its
    index table, whose sortable attribute per kind is already decided once in
    ``_predicates.SORT_ATTR`` (``target_uuid`` for a relation, ``value`` for
    everything else). Both come out of ``tables``, so an aggregate over a
    collection type reads that collection's tables (Phase 5 §6.3).
    """
    if name in FIXED_COLUMNS:
        return fixed_expression(tables.record, name), FIXED_KIND[name], None, False
    field = resolve(rtype, indexed, declared, name)
    table = tables.index[field.kind]
    return getattr(table, SORT_ATTR[field.kind]), field.kind, (table, field.key), field.many


def _on(record: Any, table: Any, type_id: int, key: str):
    """The join condition every index table is reached through here: this
    record, this type, this field key. One spelling, so the group join and the
    metric join cannot drift into meaning different things."""
    return and_(table.record_id == record.id, table.type_id == type_id, table.field_key == key)


def _check_metric(metric: Metric, kind: IndexKind, many: bool) -> None:
    if metric.op == "sum":
        if kind not in SUM_KINDS:
            raise QueryError(
                metric.field or "metric",
                "unsupported_op",
                f"sum needs a number field; {metric.field!r} is {kind.value}",
            )
        if many:
            raise QueryError(
                metric.field or "metric",
                "unsupported_op",
                f"sum over the multi-valued field {metric.field!r} would add each record's "
                "value once per value it holds",
            )
    elif kind not in ORDER_KINDS:
        raise QueryError(
            metric.field or "metric",
            "unsupported_op",
            f"{metric.op} needs an ordered field; {metric.field!r} is {kind.value}",
        )


def aggregate_query(
    rtype,
    fields: list[dict[str, Any]],
    filters,
    *,
    group_by: str,
    metric: Metric,
    cap: int,
) -> tuple[Select, IndexKind]:
    """The statement, and the kind of the values its first column returns.

    ``LIMIT cap + 1`` for the same reason the bounded count uses it (F4): one
    row past the ceiling is the whole difference between "there are exactly
    this many groups" and "there are more", and the caller reads it as
    ``truncated``.

    Ordered by count descending and then by the group value, which is a total
    order — without the tiebreaker two groups of equal size swap places
    between requests and a dashboard's rows jump.
    """
    tables = tables_for(rtype)
    record = tables.record
    indexed, declared = indexed_map(fields), declared_keys(fields)
    group_expr, group_kind, group_join, _ = _column(tables, rtype, indexed, declared, group_by)

    counted = func.count(distinct(record.id)).label("group_count")
    columns: list[Any] = [group_expr.label("group_value"), counted]
    metric_join = None
    if metric.field is not None:
        expr, kind, join, many = _column(tables, rtype, indexed, declared, metric.field)
        _check_metric(metric, kind, many)
        if join is not None:
            # Always aliased: the metric may read the *same* table as the
            # group under a different field key, which SQLAlchemy cannot
            # express as two bare references to one mapper.
            alias = aliased(join[0])
            expr = getattr(alias, SORT_ATTR[kind])
            metric_join = (alias, join[1])
        columns.append(getattr(func, metric.op)(expr).label("metric_value"))

    stmt = select(*columns).select_from(record).where(record.type_id == rtype.id)
    if group_join is not None:
        stmt = stmt.join(group_join[0], _on(record, group_join[0], rtype.id, group_join[1]))
    if metric_join is not None:
        stmt = stmt.outerjoin(metric_join[0], _on(record, metric_join[0], rtype.id, metric_join[1]))
    stmt = filtered(stmt, rtype, fields, filters)
    stmt = stmt.group_by(group_expr).order_by(desc(counted), group_expr).limit(cap + 1)
    return stmt, group_kind
