"""One number about a public type, for the live stats block (#88).

The admin aggregate (``endpoints/api/aggregate.py``) says why an anonymous
aggregate is an oracle: ``group_by=status`` counts the drafts, and a
``min``/``max`` asked under narrowing filters reconstructs one row's value at
a time. What this answers is therefore the smallest thing a public page can
already show, summed:

* **``count``** — the listing's ``total``, without the page, and bounded
  exactly as it is: :func:`~sm_records.index.query.bounded_count_query` at
  ``max_count``, so past the ceiling the value is ``max_count`` and
  ``capped`` is true. Same type gate (:func:`~sm_records.services.public.get_public_type`), same
  narrowing (:func:`~sm_records.services.public._narrow_for`: published, the
  bound tenant, one language), same filter allow-list
  (:func:`~sm_records.services.public._check_columns`).
* **``sum:<field>``** — over a field the public shape carries, so every term
  of the sum is already readable in the listing. The summed field goes through
  the same allow-list as a filter: a hidden fixed column (``position``) or a
  provider's virtual field is the 400 a filter on it is, because a sum under a
  filter that keeps one row *is* that row's value.

``min`` and ``max`` are refused even over a public field. Not because they
leak — over public fields they do not — but because the block has no use for
them and every metric this surface answers is one more question about the
data it has to keep answering safely.

**Bounded, both of them.** One row comes back, but an unbounded aggregate
still reads every matching row: an anonymous caller could make every request
a full scan of the largest public type. The count stops at ``max_count + 1``
as the listing's does. A sum reads at most ``max_count + 1`` matching records
(:func:`~sm_records.index.aggregate.bounded_sum_query`), and when more match
it answers ``None`` with ``capped`` — a sum of the first ``max_count`` rows
is not the sum, and "not available" is the honest answer. The filter count
is bounded before any of this, by ``parse_filters``' ``max_filter_terms``,
the listing's dependency. Both statements reuse the grammar unchanged, so a
``filter=`` means here what it means on the listing.

The locale is resolved by the endpoint, through the one helper the listing
uses, and is **always** applied: a translated record counts once, and a
language the site has stopped publishing never counts.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.aggregate import Metric, bounded_sum_query, parse_metric
from sm_records.index.query import Filter, FilterOp, QueryError, bounded_count_query
from sm_records.models import RecordType, tables_for
from sm_records.services.public import _check_columns, _narrow_for

__all__ = ["PUBLIC_METRICS", "UnsupportedMetricError", "public_stat"]

PUBLIC_METRICS = frozenset({"count", "sum"})
"""What the anonymous surface answers. See the module docstring for ``min``/``max``."""


def _number(value: Decimal | float | int | None) -> int | float:
    """The database's sum as JSON can carry it: an int when it is whole.

    ``SUM`` over the ``NUMERIC`` index column is a ``Decimal`` (and ``NULL``
    over no rows, which is a sum of nothing: ``0``). A whole value becomes an
    ``int`` so ``1284`` is not served as ``1284.0``; anything else is a
    ``float``. The sum is returned as the database computed it, not rounded:
    SQLite adds floats (``0.1 + 0.2`` is ``0.30000000000000004``), Postgres
    ``numeric`` is exact (``0.3``). The block rounds for display.
    """
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    number = Decimal(str(value)) if isinstance(value, float) else value
    return int(number) if number == number.to_integral_value() else float(number)


class UnsupportedMetricError(ValueError):
    """``?metric=`` is not ``count`` or ``sum:<field>``, or the summed field is
    not a single-valued number.

    Not a ``QueryError``: the endpoint flattens those into "cannot filter or
    sort by <field>", which is the wrong sentence about a metric — and telling
    the two apart by ``QueryError.field == "metric"`` would misreport a refused
    *field* that happens to be called ``metric``.
    """


def _public_metric(raw: str | None) -> Metric:
    """``?metric=`` parsed by the admin grammar, then held to :data:`PUBLIC_METRICS`."""
    try:
        metric = parse_metric(raw)
    except QueryError:
        metric = None
    if metric is None or metric.op not in PUBLIC_METRICS:
        raise UnsupportedMetricError(f"{raw!r} is not a supported metric: use count or sum:<field>")
    return metric


async def public_stat(
    db: AsyncSession,
    rtype: RecordType,
    *,
    metric: str | None,
    filters: Sequence[Filter],
    locale: str,
    cap: int,
) -> tuple[int | float | None, bool]:
    """``(value, capped)`` for ``count`` (the default, ``metric=None``) or
    ``sum:<field>`` over the published records of a public type; ``cap`` is
    ``RecordsSettings.max_count``.

    ``rtype`` comes from :func:`~sm_records.services.public.get_public_type`
    and ``locale`` is already resolved (``endpoints.api.public._locale``), in
    that order, as the listing does them — so a private type is the shared 404
    before a bad locale can be a 400. A metric this surface does not answer is
    :class:`UnsupportedMetricError`; every other refusal is a ``QueryError`` the
    endpoint flattens into the 400 naming the field.
    """
    asked = _public_metric(metric)
    # The summed field goes through the filter allow-list by name: only
    # ``field`` is read, and "may an anonymous caller ask about this column"
    # is one question whether it is filtered on or added up.
    summed = [] if asked.field is None else [Filter(field=asked.field, op=FilterOp.EQ)]
    _check_columns(rtype, [*filters, *summed], [])
    fields = list(rtype.fields or [])
    narrow = _narrow_for(tables_for(rtype).record, locale)
    if asked.field is None:
        stmt = bounded_count_query(rtype, fields, filters, cap=cap, narrow=narrow)
        counted = int((await db.execute(stmt)).scalar_one())
        return (cap, True) if counted > cap else (counted, False)
    try:  # the summed field alone: a filter's refusal below must stay a filter's
        bounded_sum_query(rtype, fields, [], metric=asked, cap=cap, narrow=narrow)
    except QueryError as exc:
        raise UnsupportedMetricError(
            f"{asked.field!r} is not a number field that can be summed"
        ) from exc
    stmt = bounded_sum_query(rtype, fields, filters, metric=asked, cap=cap, narrow=narrow)
    matched, total = (await db.execute(stmt)).one()
    return (None, True) if matched > cap else (_number(total), False)
