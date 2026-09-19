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

from sm_records.constants import ORPHANED_KEY
from sm_records.index.query import Filter, Sort, build_query, count_query
from sm_records.index.writer import write_index
from sm_records.models import Record, RecordStatus, RecordType, RevisionEvent
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

# Re-exported: ``read_view`` lives in ``_payload`` with the rest of the
# payload reading, and is imported from here by the contracts layer.
from sm_records.services._payload import read_view
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


def _migrate_orphaned(
    record: Record,
    defs: list[FieldDefinition],
    stored: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The lazy destructive migration of §8.3, run on this one record.

    Two moves, both against the *stored* payload and neither ever bulk:

    * a top-level key the current schema no longer declares is a deleted
      field's value. It moves under ``_orphaned`` — which is what makes a
      mis-clicked field deletion undoable, at the cost of some storage, and
      why nothing rewrites the whole type when a field goes (§8.2).
    * a key the schema *does* declare is dropped from ``_orphaned``: the field
      came back and its value is live again. The read path already served it
      from there (``schema.compile.from_stored``), so by now it is in ``stored``
      — either as the value the client sent back or as the field's default.

    ``_orphaned`` itself is never client-supplied (``_payload.validate``
    refuses a payload carrying it), so an update that does not mention it must
    not be read as "delete it": what survives here is carried across.

    ``extra`` is this module's own contribution to that sub-key, and the only
    way anything reaches it besides the record's own payload — see
    ``update_record``'s ``orphaned_extra``. It wins over what the record
    carried, because the one caller is a revision restore: putting an older
    payload back means putting back *its* value for a key the schema has since
    dropped, not the one a later edit left behind.
    """
    previous = dict(record.data or {})
    declared = {field.key for field in defs}
    orphaned = dict(previous.get(ORPHANED_KEY) or {})
    for key, value in previous.items():
        if key == ORPHANED_KEY or key in declared:
            continue
        orphaned.setdefault(key, value)
    for key, value in (extra or {}).items():
        if key != ORPHANED_KEY and key not in declared:
            orphaned[key] = value
    for key in declared:
        orphaned.pop(key, None)
    return {**stored, ORPHANED_KEY: orphaned} if orphaned else stored


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
    event: RevisionEvent = RevisionEvent.UPDATE,
    orphaned_extra: dict[str, Any] | None = None,
) -> Record:
    """Write a record, restamping it at the type's current schema version.

    That restamp is the lazy half of §8.3: a row written under schema 3 and
    edited under schema 5 validates against 5 and stamps 5, so payloads
    migrate one edit at a time and never in a job that can half-fail.

    ``event`` is what the appended revision records. It is a parameter because
    a restore (``services.revisions.restore``) is an ordinary write in every
    respect except how the history should read: ``RESTORE`` rather than an
    update that mysteriously repeats an older payload.

    ``orphaned_extra`` is **internal only**: keys to file under ``_orphaned``
    on this row, merged server-side *after* validation. It is not the client's
    ``_orphaned`` rule being relaxed — ``_payload.validate`` still refuses an
    inbound payload that carries the key, and no endpoint passes this. Its one
    caller is ``services.revisions.restore``, which has to put the undeclared
    half of an older payload somewhere rather than drop it on the floor
    (``extra="forbid"`` would otherwise make every revision older than a field
    deletion a permanent 422).
    """
    defs, values, stored = await _prepare(db, rtype, data, settings, exclude_id=record.id)
    stored = _migrate_orphaned(record, defs, stored, orphaned_extra)
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

    await write_revision(db, record, event, limit=settings.revision_limit, actor=actor)
    await write_index(db, record, rtype, resolve_type_id=await type_resolver(db))
    return record
