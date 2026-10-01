"""Which records match — the filter half of the grammar.

Split out of :mod:`sm_records.index.query` for the 300-line cap, along the
seam that module's docstring already drew: this one answers "does this record
match the term", ``_sorting`` answers "in what order do the matches come
back", and ``query`` is the façade that resolves a name and assembles a
statement out of both.

*A semi-join, not a JOIN and not a correlated EXISTS.* A ``multiselect`` has
one index row per value, so an inner join would return the record once per
matching row; ``Record.id IN (SELECT record_id FROM idx WHERE ...)`` asks
whether any row matches and returns the record once, because ``IN``
deduplicates. It is not the correlated ``EXISTS`` it replaced either: that
form made the subquery a function of the outer row, so its cost was (records
of the type) x (work per probe) and SQLite — given two usable indexes and no
``sqlite_stat1`` — regularly picked the value index and then filtered its
whole matching range by ``record_id`` once per record of the type. The
semi-join runs once, from the index rows that match, and is therefore
proportional to *what matches* rather than to how big the type is, on every
backend and with or without statistics.

*No soft-delete predicate anywhere*, for the reason :mod:`sm_records.index.query`
gives: the statement selects the ``Record`` entity and the framework's
``with_loader_criteria`` hook adds ``is_deleted IS false`` at execute time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.sql import ColumnElement

from sm_records.index import providers
from sm_records.index._fields import IndexedField, declared_keys, indexed_map, virtual_field
from sm_records.index._fixed import FIXED_COLUMNS, fixed_clause
from sm_records.index._predicates import FilterOp, QueryError, value_clause
from sm_records.models import RecordType, TableSet, tables_for

logger = logging.getLogger(__name__)

__all__ = ["Filter", "filtered", "resolve"]


@dataclass(frozen=True, slots=True)
class Filter:
    field: str
    op: FilterOp
    value: Any = None


def resolve(rtype: RecordType, indexed: dict[str, IndexedField], declared: set[str], name: str):
    """Which of the three refusals applies, in the order that matters.

    ``reindex_pending`` is checked *first*: mid-move a field's rows exist in
    two tables at once, and whether the definition already says ``indexed``
    depends on where the sequence of §8.5 got to. The temporary answer (409)
    has to win over the permanent one (400), or a caller retries something
    that will never start working.

    ``reindex_pending`` is a mapping of key → enqueued-at, so membership is a
    key test. Its reserved ``"*"`` entry (a whole-type ``display_title``
    rebuild) is unreachable here: no field key can be ``*``.

    A key the type does not declare may still be a **virtual field** — one an
    index provider projects (design §7.6). Resolving it here, between
    ``declared`` and the ``unknown`` refusal, is what makes a provider-only
    key queryable at all: it behaves as an indexed declared field of its kind,
    with the same operator matrix, the same ``many`` reading of ``eq``/``ne``
    and the same §7.4 truncation re-check. It is never refused as
    ``reindexing`` — see :class:`~sm_records.index.providers.VirtualField`.

    **A declared field of the same key wins.** ``validate_fields`` refuses the
    key, so the two can only collide on a type stored before the provider was
    registered; that type has real rows written from its own definition, and
    refusing its filter — or answering it from the provider's rows — would
    break a type that works. The collision is logged once per type instead.
    """
    virtual = providers.virtual_fields().get(name)
    if name in declared:
        if virtual is not None and providers.note_shadowed(rtype.key, name):
            logger.warning(
                "records: type %r declares field %r, which an index provider also projects as a "
                "virtual field; the declared field wins, so that provider's rows under the key "
                "are not queryable on this type",
                rtype.key,
                name,
            )
    elif virtual is not None:
        return virtual_field(virtual.key, virtual.kind, virtual.many)
    if name in (rtype.reindex_pending or {}):
        raise QueryError(name, "reindexing", f"{name!r} is being reindexed")
    if name not in declared:
        raise QueryError(name, "unknown", f"{name!r} is not a field of {rtype.key!r}")
    field = indexed.get(name)
    if field is None:
        raise QueryError(name, "not_indexed", f"{name!r} is not indexed, so it is not queryable")
    return field


def _holders(
    tables: TableSet, field: IndexedField, type_id: int, clause: ColumnElement[bool] | None
) -> Select:
    """The ids of the records holding an index row that matches.

    Uncorrelated on purpose — see the module docstring. ``record_id`` is
    ``NOT NULL`` on every index table, which is what makes the negated form
    (``NOT IN``) safe: a NULL anywhere in this result would make ``NOT IN``
    unknown for every row and silently empty the page.

    ``tables`` decides *which* index table, and the ids it returns are ids in
    that same set's record table — a semi-join never crosses a collection
    (Phase 5 §6.3).
    """
    table = tables.index[field.kind]
    conditions = [table.type_id == type_id, table.field_key == field.key]
    if clause is not None:
        conditions.append(clause)
    return select(table.record_id).where(*conditions)


def _term(
    tables: TableSet, rtype: RecordType, indexed, declared, flt: Filter
) -> ColumnElement[bool]:
    record = tables.record
    if flt.field in FIXED_COLUMNS:
        return fixed_clause(record, flt.field, flt.op, flt.value)
    field = resolve(rtype, indexed, declared, flt.field)
    if flt.op is FilterOp.IS_NULL:
        holders = _holders(tables, field, rtype.id, None)
        # "has no value" is the absence of any row, so it is the negation of
        # the whole semi-join — not a predicate over one row.
        return record.id.not_in(holders) if flt.value in (None, True) else record.id.in_(holders)
    clause = value_clause(tables.index[field.kind], field.kind, flt.op, flt.value, flt.field)
    holders = _holders(tables, field, rtype.id, clause)
    # ``ne`` negates the whole semi-join: "no value equals x". On a
    # multi-valued field the other reading — "some value differs" — matches a
    # record that also holds x, which nobody asking for ``ne`` wants. ``eq``
    # on the same field is the ``any`` reading, which ``IN`` gives directly.
    return record.id.not_in(holders) if flt.op is FilterOp.NE else record.id.in_(holders)


def filtered(stmt: Select, rtype: RecordType, fields: list[dict[str, Any]], filters) -> Select:
    """Apply every filter to ``stmt`` — the one place a term is built, so the
    page, its total and the ``unique`` check of §7.8 cannot drift apart.

    The table set is resolved from ``rtype`` here rather than threaded in by
    every caller (Phase 5 §6.3): a filter is always about one type, and the
    type is what says which tables its documents live in.
    """
    tables = tables_for(rtype)
    indexed = indexed_map(fields)
    declared = declared_keys(fields)
    for flt in filters:
        stmt = stmt.where(_term(tables, rtype, indexed, declared, flt))
    return stmt
