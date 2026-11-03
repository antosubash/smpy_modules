"""index _query_sort helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sm_records.models import RecordType, tables_for
from sm_records.records.index._fields import declared_keys, indexed_map
from sm_records.records.index._filters import resolve
from sm_records.records.index._fixed import FIXED_COLUMNS
from sm_records.records.index._sorting import SortTerm, fixed_term, indexed_term


@dataclass(frozen=True, slots=True)
class Sort:
    field: str
    desc: bool = False


def sort_terms(rtype: RecordType, indexed, declared, sorts: Iterable[Sort]) -> list[SortTerm]:
    """Resolve each requested sort to a :class:`~sm_records.records.index._sorting.SortTerm`.

    The refusals are :func:`sm_records.records.index._filters.resolve`'s, unchanged —
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
