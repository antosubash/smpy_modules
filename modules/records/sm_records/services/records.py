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
* **A soft delete keeps its index rows** (§7.3). Queries join back to the
  document row, where the framework's filter hides it, so the trash keeps its
  slug and its ``unique`` claims and a restore finds them intact.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.providers import TypeIndex
from sm_records.index.reduce import snapshot
from sm_records.index.writer import write_index

# Re-exported: which language a create writes in is locale policy, and lives
# with the rest of it in :mod:`sm_records.locales`.
from sm_records.locales import resolve_locale
from sm_records.models import Record, RecordStatus, RecordType, RevisionEvent, new_uuid, tables_for
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

# Re-exported: ``read_view`` lives in ``_payload`` with the payload reading.
from sm_records.services._payload import read_view

# Re-exported: a translation is an ordinary record, so the two functions that
# make one and list one live beside the lifecycle they are part of — in
# ``_translations`` only for the file cap.
from sm_records.services._translations import create_translation, list_translations
from sm_records.services.errors import Conflict, NotFound
from sm_records.services.revisions import write_revision
from sm_records.settings import RecordsSettings

__all__ = [
    "RecordListPage",
    "create_record",
    "create_translation",
    "get_deleted_record",
    "get_record",
    "hard_delete_record",
    "list_records",
    "list_translations",
    "purge_type_records",
    "read_view",
    "resolve_locale",
    "restore_record",
    "soft_delete_record",
    "update_record",
]


async def _by_uuid(db: AsyncSession, rtype: RecordType, uuid: str, *, trashed: bool) -> Record:
    """One record of ``rtype`` by uuid, out of whichever table set it lives in
    (Phase 5 §6.3). ``trashed`` lifts the framework's soft-delete filter, which
    is the only way to load a row it hides — restore and purge both need it."""
    cls = tables_for(rtype).record
    stmt = select(cls).where(cls.uuid == uuid, cls.type_id == rtype.id)
    if trashed:
        stmt = stmt.execution_options(include_deleted=True)
    record = (await db.execute(stmt)).scalars().first()
    if record is None:
        raise NotFound(f"no {rtype.key} record with uuid {uuid!r}")
    return record


async def get_record(db: AsyncSession, rtype: RecordType, uuid: str) -> Record:
    return await _by_uuid(db, rtype, uuid, trashed=False)


async def get_deleted_record(db: AsyncSession, rtype: RecordType, uuid: str) -> Record:
    """The trash view."""
    return await _by_uuid(db, rtype, uuid, trashed=True)


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
    exclude_id: int | None,
    group: str,
) -> _Prepared:
    """Validate, then the two checks no database constraint can make.

    The type row is locked before them and not before validation: the lock
    exists to close the check-then-act window of §7.8, and holding it across
    pydantic's work would serialise writes on a type for no benefit.

    ``group`` is the write's translation group, known by both write paths
    before they call: siblings are exempt from each other's ``unique`` claims
    (:func:`sm_records.services._claims.ensure_unique`).
    """
    defs = _payload.field_defs(rtype)
    values, stored = _payload.validate(
        rtype, defs, data, max_payload_bytes=settings.max_payload_bytes
    )
    await _claims.lock_type(db, rtype)
    types = await type_id_map(db)
    await _relations.check_targets(db, defs, values, types)
    await _claims.ensure_unique(db, rtype, defs, values, exclude_id=exclude_id, exclude_group=group)
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
    locale: str | None = None,
    translation_group: str | None = None,
) -> Record:
    """Write a new record, in one language, in its own translation group.

    ``locale`` defaults to the configured default content locale and is fixed
    from here on — there is no ``locale`` on the update path (§4.3).
    ``translation_group`` defaults to the record's **own uuid**, which is what
    makes a record with no siblings alone in a group named after itself; only
    :func:`sm_records.services._translations.create_translation` and the
    importer pass one, and the first only ever the source's.
    """
    resolved_locale = resolve_locale(rtype, settings, locale)
    # Both identifiers generated here rather than by two ``default_factory``
    # calls: they have to be the *same* string for a record with no siblings —
    # and before the checks rather than after, because the group is what
    # exempts a translation from its source's ``unique`` claims.
    uuid = new_uuid()
    own_group = translation_group or uuid
    _, values, stored, types = await _prepare(db, rtype, data, settings, None, own_group)
    resolved_slug = _payload.slug_for(rtype, values, slug)
    await _claims.ensure_slug_free(db, rtype, resolved_slug, resolved_locale)

    record = tables_for(rtype).record(
        uuid=uuid,
        type_id=rtype.id,
        data=stored,
        schema_version=rtype.schema_version,
        version=1,
        status=status,
        slug=resolved_slug,
        locale=resolved_locale,
        translation_group=own_group,
        display_title=_payload.display_title(rtype, values),
        position=position,
        published_at=utcnow() if status is RecordStatus.PUBLISHED else None,
        created_by=actor,
    )
    db.add(record)
    await _claims.flush_write(db, rtype, resolved_slug, resolved_locale)

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
    # Read before anything is assigned to the row: the reduce index is
    # maintained by *moving* this record from the group its old payload put
    # it in to the group its new one does (Phase 5 §5.2), and by the time
    # ``write_index`` runs ``record.data`` is already the new value. This is
    # the one place the old payload still exists.
    previous_data = dict(record.data or {})
    own_group = record.translation_group
    defs, values, stored, types = await _prepare(db, rtype, data, settings, record.id, own_group)
    stored = _payload.migrate_orphaned(record, defs, stored, orphaned_extra)
    resolved_slug = _payload.slug_for(rtype, values, slug)
    # ``record.locale`` and never an argument: a record's language is fixed for
    # its lifetime (§4.3), so the namespace this claim is made in is the row's
    # own and cannot be steered by a caller.
    await _claims.ensure_slug_free(db, rtype, resolved_slug, record.locale, exclude_id=record.id)

    record_cls = tables_for(rtype).record
    if not await guarded_bump(db, record_cls, record.id, expected_version):
        raise Conflict(
            f"record {record.uuid} has changed since it was read",
            current=await reload(db, record_cls, record.id),
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
    await _claims.flush_write(db, rtype, resolved_slug, record.locale)

    await write_revision(db, record, event, limit=settings.revision_limit, actor=actor)
    await write_index(
        db,
        record,
        rtype,
        resolve_type_id=TypeIndex(types),
        previous=snapshot(record, previous_data),
    )
    return record
