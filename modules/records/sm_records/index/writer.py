"""Writing a record's index rows — delete-then-insert, never patch.

The whole set for a record is rewritten on every write. Diffing the entries
against the stored rows would be fewer statements and one more thing that can
drift, and drift here produces *wrong query results, not slow ones* (design
doc §7.7). A record has a handful of indexed fields; the delete is a single
indexed statement per table.

Nothing here commits. The framework's ``get_db`` commits the request's
session if — and only if — something was written, so a commit in this layer
would break the caller's ability to roll the whole write back.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import TEXT_INDEX_LEN
from sm_records.index._reduce_write import apply_delta
from sm_records.index._registry import provider_name
from sm_records.index.providers import (
    IndexEntry,
    TypeResolver,
    note_dropped,
    providers,
    schema_provider,
    use_type_resolver,
    virtual_fields,
)
from sm_records.models import Record, RecordType, TableSet, tables_for
from sm_records.schema.types import IndexKind
from sm_records.services._common import utcnow

logger = logging.getLogger(__name__)


def _text_values(value: str) -> dict:
    """The §7.4 split: the first ``TEXT_INDEX_LEN`` characters are what the
    B-tree covers, and the untruncated value is kept *only* when there is more
    of it. ``value_full IS NULL`` is therefore the signal that ``value`` is the
    whole string, which is exactly what an equality filter re-checks."""
    return {
        "value": value[:TEXT_INDEX_LEN],
        "value_full": value if len(value) > TEXT_INDEX_LEN else None,
    }


def row_values(
    tables: TableSet, entry: IndexEntry, record_id: int, type_id: int
) -> tuple[type, dict]:
    """One index row as ``(table, column values)``, in ``tables``'s own set.

    Split from :func:`_row` so the two writers project identically. The
    incremental path turns this into an ORM instance; the batched rebuild
    (:mod:`sm_records.index.reindex`) hands the mappings straight to
    ``insert(Table)``, which is what lets a batch cost one statement per table
    instead of one per row. Both therefore write the same bytes by
    construction rather than by two implementations agreeing — and
    ``tests/test_index_reindex.py`` pins that they do.
    """
    base = {"record_id": record_id, "type_id": type_id, "field_key": entry.field_key}
    table = tables.index[entry.kind]
    if entry.kind is IndexKind.TEXT:
        return table, {**base, **_text_values(str(entry.value))}
    if entry.kind is IndexKind.NUMBER:
        return table, {**base, "value": Decimal(entry.value)}
    if entry.kind is IndexKind.BOOL:
        return table, {**base, "value": bool(entry.value)}
    if entry.kind is IndexKind.DATE:
        value: date = entry.value
        return table, {**base, "value": value}
    if entry.kind is IndexKind.DATETIME:
        moment: datetime = entry.value
        return table, {**base, "value": moment}
    target_uuid, target_type_id = entry.value
    return table, {**base, "target_uuid": target_uuid, "target_type_id": int(target_type_id)}


def _row(tables: TableSet, entry: IndexEntry, record_id: int, type_id: int):
    table, values = row_values(tables, entry, record_id, type_id)
    return table(**values)


def _keep(
    entry: IndexEntry,
    provider_name: str,
    declared: dict[str, Any],
    known_type_ids: frozenset[int] | None,
) -> bool:
    """Whether one entry from a *host's* provider is written, with a reason
    logged once per provider and key when it is not.

    Two ways a provider's entry is not what it says it is, both of which
    produce wrong answers rather than errors — which §7.7 is the argument
    against:

    * its ``kind`` disagrees with the :class:`~sm_records.index.providers.VirtualField`
      the same key was registered with. The row lands in one table and every
      filter over the key reads another, so the key answers ``is_null: true``
      for a record that has a value and never matches an ``eq``.
    * it is a ``REF`` naming a ``target_type_id`` that is not a type. A
      reference is load-bearing here — ``_relations`` reads
      ``records_index_ref`` to answer "what points at this record", and
      ``on_delete`` falls back to ``restrict`` for a field key it cannot
      find — so an invented one makes an unrelated record undeletable and
      puts a row nobody wrote in the delete dialog. §7.6 sells a provider as
      additive projection; participating in referential integrity is not
      part of that.

    ``declared`` is the virtual-field registry, read once per projection
    rather than per entry. ``known_type_ids`` is ``None`` when the caller's
    resolver cannot say (a
    bare callable rather than a
    :class:`~sm_records.index.providers.TypeIndex`), and the ``REF`` check is
    then skipped rather than guessed at.
    """
    virtual = declared.get(entry.field_key)
    if virtual is not None and entry.kind is not virtual.kind:
        if note_dropped(provider_name, entry.field_key):
            logger.warning(
                "records: index provider %s yields %s rows under virtual field %r, which is "
                "registered as %s; those rows are dropped — nothing could ever read them",
                provider_name,
                entry.kind.value,
                entry.field_key,
                virtual.kind.value,
            )
        return False
    if entry.kind is not IndexKind.REF:
        return True
    pair = entry.value if isinstance(entry.value, tuple) and len(entry.value) == 2 else None
    target_type_id = pair[1] if pair is not None else None
    if pair is not None and (known_type_ids is None or target_type_id in known_type_ids):
        return True
    if note_dropped(provider_name, entry.field_key):
        logger.warning(
            "records: index provider %s yields a reference under %r targeting %r, which is "
            "not a record type; those rows are dropped — a provider may not create "
            "references, which block deletes and appear as referrers",
            provider_name,
            entry.field_key,
            target_type_id if pair is not None else entry.value,
        )
    return False


def project(record: Record, rtype: RecordType, resolve_type_id: TypeResolver) -> list[IndexEntry]:
    """Every index entry ``record`` yields under ``rtype``'s definitions.

    The registry walk of §7.6 in one place, so the incremental writer and the
    batched rebuild see the same providers in the same order, and the one
    place a host provider's entries are checked against what it registered
    (:func:`_keep`). A list and not a
    generator: the resolver is bound in a context variable for the duration of
    the walk (:func:`~sm_records.index.providers.use_type_resolver`), and a
    generator would leave that binding's lifetime to whoever happens to stop
    iterating.

    **Each registered provider is isolated.** One that raises is logged and
    skipped, and the write carries on with the others: a host's broken
    extension must not make every record of every type unsaveable. The
    built-in ``schema_provider`` is deliberately not wrapped — it failing is a
    bug in this module, and hiding it would turn a traceback into silently
    missing index rows, which §7.7 is the argument against.
    """
    entries: list[IndexEntry] = []
    declared = virtual_fields()
    known_type_ids = getattr(resolve_type_id, "known_ids", None)
    with use_type_resolver(resolve_type_id):
        for provider in providers():
            if provider is schema_provider:
                # Not guarded: the built-in projection raising is a bug in
                # this module, and swallowing it would turn it into missing
                # index rows — a wrong query result rather than a traceback.
                entries.extend(provider(record, rtype))
                continue
            name = provider_name(provider)
            try:
                produced = list(provider(record, rtype))
            except Exception:
                # A host's provider must not make every record of every type
                # unsaveable. Its rows are simply missing until the bug is
                # fixed and ``cli reindex`` has run, which is the same state
                # a provider registered late leaves behind.
                logger.exception(
                    "records: index provider %s failed on record %s; its rows are missing",
                    name,
                    record.uuid,
                )
                continue
            # Materialised before it is appended: a generator that raises
            # halfway would otherwise leave the entries it had already
            # yielded in the set, which is half a projection written as if
            # it were whole. Filtered on the way in — see :func:`_keep`.
            entries.extend(e for e in produced if _keep(e, name, declared, known_type_ids))
    return entries


async def delete_index(db: AsyncSession, tables: TableSet, record_id: int) -> None:
    """Remove every index row of a record, across all six of its tables.

    Called on a **hard** delete only. A soft delete leaves the rows in place on
    purpose: index rows carry no record state, and every query joins back to
    ``records_record``, where the framework's ``with_loader_criteria`` filter
    hides the row (design doc §7.3). Deleting them on a soft delete would mean
    rebuilding them on restore, from a payload that may no longer validate.
    """
    for table in tables.index_tables:
        await db.execute(delete(table).where(table.record_id == record_id))


async def write_index(
    db: AsyncSession,
    record: Record,
    rtype: RecordType,
    *,
    resolve_type_id: TypeResolver,
    fresh: bool = False,
    previous: Record | None = None,
) -> None:
    """Rebuild every index row for ``record`` from its payload.

    ``type_id`` on the rows comes from ``rtype`` rather than from the record:
    the entries were projected through *this* type's field definitions, and a
    row discriminated by any other type id would be invisible to every query
    that reads them.

    ``fresh`` says the caller knows this record has no index rows yet, and the
    six-table delete pass is skipped. It defaults to ``False`` — the safe,
    unconditional behaviour — because being wrong about it leaves *duplicate*
    index rows, which is a wrong query result rather than a slow one (§7.7),
    and only a caller that inserted the row itself in this transaction can
    assert it. :func:`sm_records.services.records.create_record` is that
    caller and the only one; the six ``DELETE``s it saves were 27-50% of a
    create, all of them guaranteed to match nothing.

    ``previous`` is the record **as it was before this write**, and it exists
    only for the reduce index: a fold cannot be rewritten from the new payload
    alone, it has to be moved off the group the old payload was in. Pass
    :func:`sm_records.index.reduce.snapshot` with the ``data`` read before the
    write. ``None`` means "this record was not counted until now" — which is
    true of a create and of a restore, and *false* of an edit. Getting it
    wrong on an edit double-counts the record, which is why ``fresh`` and
    ``previous`` together are refused outright rather than silently reconciled.
    """
    if fresh and previous is not None:
        raise ValueError("write_index: 'fresh' is a create, which has no previous state")
    tables = tables_for(rtype)
    if record.id is None:
        # A freshly-created record has no id until it hits the DB, and index
        # rows are keyed on it. Flushing here rather than making the caller
        # remember keeps "create then index" a two-liner at the call site.
        await db.flush()

    if not fresh:
        await delete_index(db, tables, record.id)

    rows = [
        _row(tables, entry, record.id, rtype.id)
        for entry in project(record, rtype, resolve_type_id)
    ]
    if rows:
        db.add_all(rows)
    await db.flush()

    # Last, and in the same transaction: the map rows above are a projection
    # of this record and can be rewritten wholesale, while a reduce row is a
    # fold over many records and can only be *moved* — from what this record
    # contributed before the write to what it contributes now (Phase 5 §5.2).
    # With no spec registered this is a ``for`` over an empty tuple and issues
    # nothing, which is what keeps the Phase 4 statement count intact.
    await apply_delta(db, rtype, before=previous, after=record, now=utcnow())
