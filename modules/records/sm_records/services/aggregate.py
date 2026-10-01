"""Running an aggregate, live or stored — the service behind ``/aggregate``.

Phase 5 §5.1 keeps two things apart that a naive reading would merge:

* **The live aggregate** is a ``GROUP BY`` over the map indexes, always
  available, never stored, and correct by construction because it reads the
  same rows the list reads through the same filter terms
  (:mod:`sm_records.index.aggregate`).
* **The stored aggregate** is a reduce index — maintained on write, opt-in per
  provider, and a second source of truth. It answers the same question far
  faster on a type where the ``GROUP BY`` has become too slow, at the cost of
  being something that can drift.

Both come back in one shape so a caller can ask the same question twice and
compare the answers, which is how an operator finds out the second source of
truth has stopped agreeing with the first without running the CLI.

Nothing here commits; nothing here writes.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.aggregate import AggregateGroup, AggregateResponse
from sm_records.index._predicates import QueryError
from sm_records.index.aggregate import Metric, aggregate_query
from sm_records.index.query import Filter
from sm_records.index.reduce import group_text, spec_for
from sm_records.models import IndexReduce, RecordType
from sm_records.settings import RecordsSettings

__all__ = ["aggregate", "stored_aggregate"]


def render(value: Any) -> str | None:
    """A cell as the response carries it: text, or ``null`` for no value.

    ``enum`` first, because ``status`` comes back as a ``RecordStatus`` and
    ``str()`` on one is ``'RecordStatus.DRAFT'`` — a group key no caller could
    match against anything. Everything else goes through
    :func:`sm_records.index.reduce.group_text`, which is the *same* renderer
    the reduce table stores its groups with: a live group and a stored group
    for the same value have to be the same string or the two readings cannot
    be compared at all.
    """
    if isinstance(value, enum.Enum):
        return group_text(value.value)
    return group_text(value)


async def aggregate(
    db: AsyncSession,
    rtype: RecordType,
    *,
    settings: RecordsSettings,
    group_by: str,
    metric: Metric,
    filters: Sequence[Filter] = (),
) -> AggregateResponse:
    """The live ``GROUP BY``. Refusals are the filter grammar's, unchanged.

    A record with no value for ``group_by`` is in **no group** rather than in
    a ``null`` one: it has no index row, so there is nothing to group it by.
    A fixed column is the exception — the column exists and may be ``NULL`` —
    and such records do come back as a group whose ``value`` is ``null``.
    """
    cap = settings.max_aggregate_groups
    stmt, _kind = aggregate_query(
        rtype, list(rtype.fields or []), filters, group_by=group_by, metric=metric, cap=cap
    )
    rows = (await db.execute(stmt)).all()
    truncated = len(rows) > cap
    groups = [_group(row, metric) for row in rows[:cap]]
    return AggregateResponse(
        group_by=group_by,
        metric=str(metric),
        groups=groups,
        total_groups=len(groups),
        truncated=truncated,
    )


def _group(row: Any, metric: Metric) -> AggregateGroup:
    value = render(row[0])
    count = int(row[1])
    if metric.field is None:
        return AggregateGroup(value=value, count=count)
    rendered = render(row[2])
    return AggregateGroup(value=value, count=count, **{metric.op: rendered})


def _stored_metric(spec: Any) -> str:
    """What a stored reading calls its own metric — see :func:`stored_aggregate`."""
    if spec.value is None:
        return "count"
    return "sum" if not spec.value_label else f"sum:{spec.value_label}"


async def stored_aggregate(
    db: AsyncSession, rtype: RecordType, *, settings: RecordsSettings, key: str
) -> AggregateResponse:
    """The maintained rows of one reduce spec, in the same shape.

    An unregistered key is a 400 naming it and **not** an empty result: a
    caller that misspelled a spec, or that is talking to a worker which never
    ran the registration, must not be told "no groups" — that is the answer
    for a spec with no records, and the two are not the same fact.

    ``metric`` reports what the **spec** declares, in the spec's own words:
    ``"count"``, or ``"sum"`` — with ``":<value_label>"`` appended when the
    spec names one. Not ``sum:<spec key>``, which is what it used to say: on a
    live reading ``sum:<x>`` names a *field*, so ``sum:by_state`` read as a
    field called ``by_state`` that no type declares. A stored fold has no
    field to name; it has a callable, and a label for it if the host wrote one.
    """
    spec = spec_for(key)
    if spec is None:
        raise QueryError("reduce", "unknown", f"{key!r} is not a registered reduce index")
    cap = settings.max_aggregate_groups
    stmt = (
        select(IndexReduce)
        .where(IndexReduce.type_id == rtype.id, IndexReduce.key == key)
        .order_by(IndexReduce.count.desc(), IndexReduce.group_value)
        .limit(cap + 1)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    truncated = len(rows) > cap
    kept = rows[:cap]
    newest = (
        await db.execute(
            select(func.max(IndexReduce.updated_at)).where(
                IndexReduce.type_id == rtype.id, IndexReduce.key == key
            )
        )
    ).scalar_one_or_none()
    return AggregateResponse(
        group_by=key,
        metric=_stored_metric(spec),
        groups=[
            AggregateGroup(
                value=row.group_value,
                count=int(row.count),
                sum=None if row.sum is None else str(row.sum),
            )
            for row in kept
        ],
        total_groups=len(kept),
        truncated=truncated,
        stored=True,
        updated_at=newest,
    )
