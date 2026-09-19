"""Record CRUD — the lifecycle of one document and its index rows.

Three rules from the design doc shape every function here and are worth
having in front of you while reading it:

* **The payload is history; the index is truth for queries** (§8.3). A write
  validates against the type's *current* schema and restamps the row, which
  is the only way a payload ever migrates. Index rows are rewritten in full on
  every write, because a stale index is a wrong answer rather than a lag.
* **Nothing here commits.** The framework's session commits the request if
  anything was written (``get_db`` plus ``CommitBeforeResponseMiddleware``), so
  a commit in this layer would take the caller's rollback away.
* **A soft delete keeps its index rows** (§7.3). Queries join back to
  ``records_record``, where the framework's filter hides the row, so the
  trash keeps its slug and its ``unique`` claims and a restore finds them
  intact.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.query import Filter, Sort, build_query, count_query
from sm_records.index.writer import write_index
from sm_records.models import Record, RecordStatus, RecordType, RevisionEvent
from sm_records.schema.compile import from_stored
from sm_records.schema.fields import FieldDefinition
from sm_records.services import _payload, _relations
from sm_records.services._common import guarded_bump, reload, type_id_map, type_resolver, utcnow

# Re-exported so the delete lifecycle is importable from the one module
# endpoints already use; it lives in ``_lifecycle`` only for the file cap.
from sm_records.services._lifecycle import (
    hard_delete_record,
    purge_type_records,
    restore_record,
    soft_delete_record,
)
from sm_records.services.errors import Conflict, NotFound
from sm_records.services.revisions import write_revision
from sm_records.settings import RecordsSettings

__all__ = [
    "create_record",
    "get_deleted_record",
    "get_record",
    "hard_delete_record",
    "list_records",
    "purge_type_records",
    "read_view",
    "restore_record",
    "soft_delete_record",
    "update_record",
]


async def list_records(
    db: AsyncSession,
    rtype: RecordType,
    *,
    settings: RecordsSettings,
    filters: Sequence[Filter] = (),
    sorts: Sequence[Sort] = (),
    page: int = 1,
    page_size: int | None = None,
) -> tuple[list[Record], int]:
    """One page of records, and the unpaged total.

    ``QueryError`` from the builder is allowed to propagate: only the endpoint
    layer knows the difference it has to express — 409 while a field is being
    reindexed, 400 for a field that is simply not queryable (§8.5).
    """
    size = min(page_size or settings.default_page_size, settings.max_page_size)
    size = max(size, 1)
    offset = max(page - 1, 0) * size
    fields = list(rtype.fields or [])
    total = int((await db.execute(count_query(rtype, fields, filters))).scalar_one())
    stmt = build_query(rtype, fields, filters, sorts).offset(offset).limit(size)
    return list((await db.execute(stmt)).scalars().all()), total


async def get_record(db: AsyncSession, rtype: RecordType, uuid: str) -> Record:
    stmt = select(Record).where(Record.uuid == uuid, Record.type_id == rtype.id)
    record = (await db.execute(stmt)).scalars().first()
    if record is None:
        raise NotFound(f"no {rtype.key} record with uuid {uuid!r}")
    return record


async def get_deleted_record(db: AsyncSession, rtype: RecordType, uuid: str) -> Record:
    """The trash view. ``include_deleted`` is the only way to load a row the
    framework's filter hides, and restore and purge both need it."""
    stmt = (
        select(Record)
        .where(Record.uuid == uuid, Record.type_id == rtype.id)
        .execution_options(include_deleted=True)
    )
    record = (await db.execute(stmt)).scalars().first()
    if record is None:
        raise NotFound(f"no {rtype.key} record with uuid {uuid!r}")
    return record


async def _prepare(
    db: AsyncSession,
    rtype: RecordType,
    data: dict[str, Any],
    settings: RecordsSettings,
    *,
    exclude_id: int | None,
) -> tuple[list[FieldDefinition], dict[str, Any], dict[str, Any]]:
    """Validate, then the two checks no database constraint can make.

    The type row is locked before them and not before validation: the lock
    exists to close the check-then-act window of §7.8, and holding it across
    pydantic's work would serialise writes on a type for no benefit.
    """
    defs = _payload.field_defs(rtype)
    values, stored = _payload.validate(
        rtype, defs, data, max_payload_bytes=settings.max_payload_bytes
    )
    await _payload.lock_type(db, rtype)
    await _relations.check_targets(db, defs, values, await type_id_map(db))
    await _payload.ensure_unique(db, rtype, defs, values, exclude_id=exclude_id)
    return defs, values, stored


async def create_record(
    db: AsyncSession,
    rtype: RecordType,
    *,
    data: dict[str, Any],
    settings: RecordsSettings,
    status: RecordStatus = RecordStatus.DRAFT,
    slug: str | None = None,
    position: int = 0,
    actor: str | None = None,
) -> Record:
    _, values, stored = await _prepare(db, rtype, data, settings, exclude_id=None)
    resolved_slug = _payload.slug_for(rtype, values, slug)
    await _payload.ensure_slug_free(db, rtype, resolved_slug)

    record = Record(
        type_id=rtype.id,
        data=stored,
        schema_version=rtype.schema_version,
        version=1,
        status=status,
        slug=resolved_slug,
        display_title=_payload.display_title(rtype, values),
        position=position,
        published_at=utcnow() if status is RecordStatus.PUBLISHED else None,
        created_by=actor,
    )
    db.add(record)
    await db.flush()

    await write_revision(
        db, record, RevisionEvent.CREATE, limit=settings.revision_limit, actor=actor
    )
    await write_index(db, record, rtype, resolve_type_id=await type_resolver(db))
    return record


def _published_at(record: Record, new_status: RecordStatus):
    """Set on publish, kept on a published-to-published edit, cleared on
    unpublish — so "when did this go live" survives every later edit but does
    not survive being taken down."""
    if new_status is not RecordStatus.PUBLISHED:
        return None
    if record.status is RecordStatus.PUBLISHED and record.published_at is not None:
        return record.published_at
    return utcnow()


async def update_record(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    *,
    expected_version: int,
    data: dict[str, Any],
    settings: RecordsSettings,
    status: RecordStatus | None = None,
    slug: str | None = None,
    position: int | None = None,
    actor: str | None = None,
) -> Record:
    """Write a record, restamping it at the type's current schema version.

    That restamp is the lazy half of §8.3: a row written under schema 3 and
    edited under schema 5 validates against 5 and stamps 5, so payloads
    migrate one edit at a time and never in a job that can half-fail.
    """
    _, values, stored = await _prepare(db, rtype, data, settings, exclude_id=record.id)
    resolved_slug = _payload.slug_for(rtype, values, slug)
    await _payload.ensure_slug_free(db, rtype, resolved_slug, exclude_id=record.id)

    if not await guarded_bump(db, Record, record.id, expected_version):
        raise Conflict(
            f"record {record.uuid} has changed since it was read",
            current=await reload(db, Record, record.id),
        )

    new_status = status or record.status
    record.published_at = _published_at(record, new_status)
    record.status = new_status
    record.data = stored
    record.schema_version = rtype.schema_version
    record.slug = resolved_slug
    record.display_title = _payload.display_title(rtype, values)
    if position is not None:
        record.position = position
    record.updated_by = actor
    record.version = expected_version + 1
    db.add(record)
    await db.flush()

    await write_revision(
        db, record, RevisionEvent.UPDATE, limit=settings.revision_limit, actor=actor
    )
    await write_index(db, record, rtype, resolve_type_id=await type_resolver(db))
    return record


def read_view(rtype: RecordType, record: Record) -> dict[str, Any]:
    """The lenient read of §8.3, plus whether this row is behind the schema.

    ``data`` is nested rather than merged with ``schema_stale`` because a
    field key may legally *be* ``schema_stale`` — ``TYPE_KEY_PATTERN`` allows
    it — and a payload key silently overwriting a status flag is the kind of
    collision that is only ever found in production.
    """
    defs = _payload.field_defs(rtype)
    return {
        "data": from_stored(defs, dict(record.data or {})),
        "schema_stale": record.schema_version != rtype.schema_version,
    }
