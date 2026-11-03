"""The bounded count: ``count_query`` that stops at ``cap + 1``.

Split out of :mod:`sm_records.records.index.query`, which re-exports
:func:`bounded_count_query` and :func:`count_columns`, so callers keep one
import path. The subject here is the one trap the bound has — keeping the
framework's per-mapper criteria attached through a ``LIMIT`` subquery — and
:func:`bounded_inner` is the shared half that
:func:`~sm_records.records.index.aggregate.bounded_sum_query` builds on too.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import cache
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import aliased

from sm_records.models import RecordType, tables_for
from sm_records.records.index._filters import Filter, filtered

__all__ = ["bounded_count_query", "bounded_inner", "count_columns"]


@cache
def count_columns(record: Any) -> tuple[Any, ...]:
    """What the bounded count's inner query selects: every column of a record
    except the payload.

    A function of the table set (Phase 5 §6.3) and memoised: there are as many
    of these tuples as there are declared collections plus one, and none of
    them changes after import.

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
    return tuple(
        getattr(record, column.key) for column in record.__table__.c if column.name != "data"
    )


def bounded_inner(
    rtype: RecordType,
    fields: list[dict[str, Any]],
    filters: Sequence[Filter],
    *,
    cap: int,
    narrow: Any = None,
) -> Select:
    """The bounded aggregates' inner query: the :func:`count_columns` of the
    records ``filters`` and ``narrow`` match, ``LIMIT cap + 1``. Shared by
    :func:`bounded_count_query` and
    :func:`~sm_records.records.index.aggregate.bounded_sum_query`, so the two bound the
    same rows; each lifts its execution options to the outer statement."""
    record = tables_for(rtype).record
    stmt = filtered(
        select(*count_columns(record)).where(record.type_id == rtype.id), rtype, fields, filters
    )
    return (narrow(stmt) if narrow is not None else stmt).limit(cap + 1)


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
    inner = bounded_inner(rtype, fields, filters, cap=cap, narrow=narrow)
    counted = aliased(tables_for(rtype).record, inner.subquery())
    stmt = select(func.count(counted.id)).select_from(counted)
    options = inner.get_execution_options()
    return stmt.execution_options(**options) if options else stmt
