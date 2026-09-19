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

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import TEXT_INDEX_LEN
from sm_records.index.providers import (
    IndexEntry,
    TypeResolver,
    providers,
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


def _text_row(base: dict, value: str) -> IndexText:
    """The §7.4 split: the first ``TEXT_INDEX_LEN`` characters are what the
    B-tree covers, and the untruncated value is kept *only* when there is more
    of it. ``value_full IS NULL`` is therefore the signal that ``value`` is the
    whole string, which is exactly what an equality filter re-checks."""
    return IndexText(
        **base,
        value=value[:TEXT_INDEX_LEN],
        value_full=value if len(value) > TEXT_INDEX_LEN else None,
    )


def _row(entry: IndexEntry, record_id: int, type_id: int):
    base = {"record_id": record_id, "type_id": type_id, "field_key": entry.field_key}
    if entry.kind is IndexKind.TEXT:
        return _text_row(base, str(entry.value))
    if entry.kind is IndexKind.NUMBER:
        return IndexNumber(**base, value=Decimal(entry.value))
    if entry.kind is IndexKind.BOOL:
        return IndexBool(**base, value=bool(entry.value))
    if entry.kind is IndexKind.DATE:
        value: date = entry.value
        return IndexDate(**base, value=value)
    if entry.kind is IndexKind.DATETIME:
        moment: datetime = entry.value
        return IndexDatetime(**base, value=moment)
    target_uuid, target_type_id = entry.value
    return IndexRef(**base, target_uuid=target_uuid, target_type_id=int(target_type_id))


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
) -> None:
    """Rebuild every index row for ``record`` from its payload.

    ``type_id`` on the rows comes from ``rtype`` rather than from the record:
    the entries were projected through *this* type's field definitions, and a
    row discriminated by any other type id would be invisible to every query
    that reads them.
    """
    if record.id is None:
        # A freshly-created record has no id until it hits the DB, and index
        # rows are keyed on it. Flushing here rather than making the caller
        # remember keeps "create then index" a two-liner at the call site.
        await db.flush()

    await delete_index(db, record.id)

    rows = []
    with use_type_resolver(resolve_type_id):
        for provider in providers():
            for entry in provider(record, rtype):
                rows.append(_row(entry, record.id, rtype.id))

    if rows:
        db.add_all(rows)
    await db.flush()
