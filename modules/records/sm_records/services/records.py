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

from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.providers import TypeIndex
from sm_records.index.writer import write_index
from sm_records.models import Record, RecordStatus, RecordType, RevisionEvent
from sm_records.schema.fields import FieldDefinition
from sm_records.services import _claims, _payload, _relations
from sm_records.services._common import guarded_bump, reload, type_id_map, utcnow

# Re-exported so the delete lifecycle is importable from the one module
# endpoints already use; it lives in ``_lifecycle`` only for the file cap.
from sm_records.services._lifecycle import (
    hard_delete_record,
    purge_type_records,
    restore_record,
    soft_delete_record,
)

# Re-exported: listing a page is a different job from the lifecycle of one
# document, and lives in ``_listing`` for that reason and for the file cap.
from sm_records.services._listing import RecordListPage, list_records

# Re-exported: ``read_view`` lives in ``_payload`` with the rest of the
# payload reading, and is imported from here by the contracts layer.
from sm_records.services._payload import read_view
from sm_records.services.errors import Conflict, NotFound
from sm_records.services.revisions import write_revision
from sm_records.settings import RecordsSettings

__all__ = [
    "RecordListPage",
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


class _Prepared(NamedTuple):
    """What both write paths need out of :func:`_prepare`.

    ``types`` rides along rather than being looked up again: ``{key: id}`` is
    read once here for the relation check and is the same mapping the index
    writer's resolver needs (``index.providers.TypeResolver``), which used to
    make ``SELECT key, id FROM records_type`` a twice-per-write statement.
    Threaded through an argument and not cached on the module: types are
    created and deleted at runtime, and a process-global map would hand a
    stale id to the one thing that must not have one — the ``relation`` rows
    ``on_delete`` is enforced from (§9).
    """

    defs: list[FieldDefinition]
    values: dict[str, Any]
    stored: dict[str, Any]
    types: dict[str, int]


async def _prepare(
    db: AsyncSession,
    rtype: RecordType,
    data: dict[str, Any],
    settings: RecordsSettings,
    *,
    exclude_id: int | None,
) -> _Prepared:
    """Validate, then the two checks no database constraint can make.

    The type row is locked before them and not before validation: the lock
    exists to close the check-then-act window of §7.8, and holding it across
    pydantic's work would serialise writes on a type for no benefit.
    """
    defs = _payload.field_defs(rtype)
    values, stored = _payload.validate(
        rtype, defs, data, max_payload_bytes=settings.max_payload_bytes
    )
    await _claims.lock_type(db, rtype)
    types = await type_id_map(db)
    await _relations.check_targets(db, defs, values, types)
    await _claims.ensure_unique(db, rtype, defs, values, exclude_id=exclude_id)
    return _Prepared(defs, values, stored, types)


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
    _, values, stored, types = await _prepare(db, rtype, data, settings, exclude_id=None)
    resolved_slug = _payload.slug_for(rtype, values, slug)
    await _claims.ensure_slug_free(db, rtype, resolved_slug)

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
    await _claims.flush_write(db, rtype, resolved_slug)

    await write_revision(
        db, record, RevisionEvent.CREATE, limit=settings.revision_limit, actor=actor
    )
    # ``fresh``: the row was inserted by the flush above, so it cannot own
    # index rows yet and the writer's six-table delete pass is skipped.
    await write_index(db, record, rtype, resolve_type_id=TypeIndex(types), fresh=True)
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
    defs, values, stored, types = await _prepare(db, rtype, data, settings, exclude_id=record.id)
    stored = _payload.migrate_orphaned(record, defs, stored, orphaned_extra)
    resolved_slug = _payload.slug_for(rtype, values, slug)
    await _claims.ensure_slug_free(db, rtype, resolved_slug, exclude_id=record.id)

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
    await _claims.flush_write(db, rtype, resolved_slug)

    await write_revision(db, record, event, limit=settings.revision_limit, actor=actor)
    await write_index(db, record, rtype, resolve_type_id=TypeIndex(types))
    return record
