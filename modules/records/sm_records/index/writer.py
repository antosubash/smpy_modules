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

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import TEXT_INDEX_LEN
from sm_records.index.providers import (
    IndexEntry,
    TypeResolver,
    providers,
    schema_provider,
    use_type_resolver,
)
from sm_records.models import (
    INDEX_TABLES,
    IndexBool,
    IndexDate,
    IndexDatetime,
    IndexNumber,
    IndexRef,
    IndexText,
    Record,
    RecordType,
)
from sm_records.schema.types import IndexKind

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


def row_values(entry: IndexEntry, record_id: int, type_id: int) -> tuple[type, dict]:
    """One index row as ``(table, column values)``.

    Split from :func:`_row` so the two writers project identically. The
    incremental path turns this into an ORM instance; the batched rebuild
    (:mod:`sm_records.index.reindex`) hands the mappings straight to
    ``insert(Table)``, which is what lets a batch cost one statement per table
    instead of one per row. Both therefore write the same bytes by
    construction rather than by two implementations agreeing — and
    ``tests/test_index_reindex.py`` pins that they do.
    """
    base = {"record_id": record_id, "type_id": type_id, "field_key": entry.field_key}
    if entry.kind is IndexKind.TEXT:
        return IndexText, {**base, **_text_values(str(entry.value))}
    if entry.kind is IndexKind.NUMBER:
        return IndexNumber, {**base, "value": Decimal(entry.value)}
    if entry.kind is IndexKind.BOOL:
        return IndexBool, {**base, "value": bool(entry.value)}
    if entry.kind is IndexKind.DATE:
        value: date = entry.value
        return IndexDate, {**base, "value": value}
    if entry.kind is IndexKind.DATETIME:
        moment: datetime = entry.value
        return IndexDatetime, {**base, "value": moment}
    target_uuid, target_type_id = entry.value
    return IndexRef, {**base, "target_uuid": target_uuid, "target_type_id": int(target_type_id)}


def _row(entry: IndexEntry, record_id: int, type_id: int):
    table, values = row_values(entry, record_id, type_id)
    return table(**values)


def project(record: Record, rtype: RecordType, resolve_type_id: TypeResolver) -> list[IndexEntry]:
    """Every index entry ``record`` yields under ``rtype``'s definitions.

    The registry walk of §7.6 in one place, so the incremental writer and the
    batched rebuild see the same providers in the same order. A list and not a
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
    with use_type_resolver(resolve_type_id):
        for provider in providers():
            if provider is schema_provider:
                # Not guarded: the built-in projection raising is a bug in
                # this module, and swallowing it would turn it into missing
                # index rows — a wrong query result rather than a traceback.
                entries.extend(provider(record, rtype))
                continue
            try:
                produced = list(provider(record, rtype))
            except Exception:
                # A host's provider must not make every record of every type
                # unsaveable. Its rows are simply missing until the bug is
                # fixed and ``cli reindex`` has run, which is the same state
                # a provider registered late leaves behind.
                logger.exception(
                    "records: index provider %s failed on record %s; its rows are missing",
                    getattr(provider, "__qualname__", None) or repr(provider),
                    record.uuid,
                )
                continue
            # Materialised before it is appended: a generator that raises
            # halfway would otherwise leave the entries it had already
            # yielded in the set, which is half a projection written as if
            # it were whole.
            entries.extend(produced)
    return entries


async def delete_index(db: AsyncSession, record_id: int) -> None:
    """Remove every index row of a record, across all six tables.

    Called on a **hard** delete only. A soft delete leaves the rows in place on
    purpose: index rows carry no record state, and every query joins back to
    ``records_record``, where the framework's ``with_loader_criteria`` filter
    hides the row (design doc §7.3). Deleting them on a soft delete would mean
    rebuilding them on restore, from a payload that may no longer validate.
    """
    for table in INDEX_TABLES:
        await db.execute(delete(table).where(table.record_id == record_id))


async def write_index(
    db: AsyncSession,
    record: Record,
    rtype: RecordType,
    *,
    resolve_type_id: TypeResolver,
    fresh: bool = False,
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
    """
    if record.id is None:
        # A freshly-created record has no id until it hits the DB, and index
        # rows are keyed on it. Flushing here rather than making the caller
        # remember keeps "create then index" a two-liner at the call site.
        await db.flush()

    if not fresh:
        await delete_index(db, record.id)

    rows = [_row(entry, record.id, rtype.id) for entry in project(record, rtype, resolve_type_id)]
    if rows:
        db.add_all(rows)
    await db.flush()
