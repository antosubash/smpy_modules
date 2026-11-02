"""One number about a public type, for the live stats block (#88).

The admin aggregate (``endpoints/api/aggregate.py``) says why an anonymous
aggregate is an oracle: ``group_by=status`` counts the drafts, and a
``min``/``max`` asked under narrowing filters reconstructs one row's value at
a time. What this answers is therefore the smallest thing a public page can
already show, summed:

* **``count``** — the listing's ``total``, without the page (and without
  its ``max_count`` bound, which exists to stop a page paying for a count).
  Same type gate (:func:`~sm_records.services.public.get_public_type`), same
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

**No ``group_by``** and so no cap: one row comes back. The statement is
:func:`~sm_records.index.aggregate.total_query`, which reuses the grouped
query's column resolution and the filter grammar unchanged, so a ``filter=``
means here what it means on the listing.

The locale is resolved by the endpoint, through the one helper the listing
uses, and is **always** applied: a translated record counts once, and a
language the site has stopped publishing never counts.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.aggregate import Metric, total_query
from sm_records.index.query import Filter, FilterOp, QueryError
from sm_records.models import RecordType, tables_for
from sm_records.services.public import _check_columns, _narrow_for

__all__ = ["PUBLIC_METRICS", "public_stat"]

PUBLIC_METRICS = frozenset({"count", "sum"})
"""What the anonymous surface answers. See the module docstring for ``min``/``max``."""


def _number(value: Decimal | float | int | None) -> int | float:
    """The exact sum as JSON can carry it: an int when it is whole.

    ``SUM`` over the ``NUMERIC`` index column is a ``Decimal`` (and ``NULL``
    over no rows, which is a sum of nothing: ``0``). A whole value becomes an
    ``int`` so ``1284`` is not served as ``1284.0``; anything else is a
    ``float``, which is exact for every value the index's scale can hold at
    the sizes a stats band shows.
    """
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    number = Decimal(str(value)) if isinstance(value, float) else value
    return int(number) if number == number.to_integral_value() else float(number)


async def public_stat(
    db: AsyncSession,
    rtype: RecordType,
    *,
    metric: Metric,
    filters: Sequence[Filter],
    locale: str,
) -> int | float:
    """``count`` or ``sum:<field>`` over the published records of a public type.

    ``rtype`` comes from :func:`~sm_records.services.public.get_public_type`
    and ``locale`` is already resolved (``endpoints.api.public._locale``), in
    that order, as the listing does them — so a private type is the shared 404
    before a bad locale can be a 400. Every refusal here is a ``QueryError``
    the endpoint flattens into the 400 naming the field.
    """
    if metric.op not in PUBLIC_METRICS:
        raise QueryError(
            "metric", "bad_value", f"{metric.op!r} is not a public metric: use count or sum"
        )
    # The summed field goes through the filter allow-list by name: only
    # ``field`` is read, and "may an anonymous caller ask about this column"
    # is one question whether it is filtered on or added up.
    summed = [] if metric.field is None else [Filter(field=metric.field, op=FilterOp.EQ)]
    _check_columns(rtype, [*filters, *summed], [])
    stmt = total_query(rtype, list(rtype.fields or []), filters, metric=metric)
    stmt = _narrow_for(tables_for(rtype).record, locale)(stmt)
    return _number((await db.execute(stmt)).scalar_one())
