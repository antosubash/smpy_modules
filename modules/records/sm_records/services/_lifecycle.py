"""The delete lifecycle: trash, restore, purge — and what relations cost.

Split out of :mod:`sm_records.services.records` for the file cap, and it is
the natural seam: everything here is about a record's *existence* rather than
its content, and all of it turns on design §9's rule that ``on_delete`` is a
property of the referring field, enforced in the service because there is no
foreign key to enforce it in the database. ``records`` re-exports these, so
callers still import one module.
"""

from __future__ import annotations

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.reindex import reindex_record
from sm_records.index.writer import delete_index, write_index
from sm_records.models import Record, RecordRevision, RecordType, RevisionEvent
from sm_records.services import _relations
from sm_records.services._common import mark_written, type_resolver, utcnow
from sm_records.services.errors import Conflict, ReferencedByOthers
from sm_records.services.revisions import write_revision
from sm_records.settings import RecordsSettings

_RESTRICT = "restrict"
_SET_NULL = "set_null"
_CASCADE = "cascade"


async def _apply_set_null(db: AsyncSession, ref: _relations.Referrer, uuid: str) -> None:
    """Drop the reference and rewrite the referrer's index rows.

    A to-many field loses only the entry that pointed at the deleted record;
    a to-one field goes to ``None``. Nulling the whole list would delete
    references to records nobody asked to delete, which is the mistake
    ``restrict``-by-default exists to avoid one level up.
    """
    data = dict(ref.record.data or {})
    value = data.get(ref.field_key)
    if isinstance(value, list):
        kept = [item for item in value if not (isinstance(item, dict) and item.get("uuid") == uuid)]
        data[ref.field_key] = kept or None
    else:
        data[ref.field_key] = None
    ref.record.data = data
    db.add(ref.record)
    await db.flush()
    await write_index(db, ref.record, ref.rtype, resolve_type_id=await type_resolver(db))


async def soft_delete_record(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    *,
    actor: str | None = None,
    settings: RecordsSettings,
    _visited: set[int] | None = None,
) -> None:
    """Trash a record, honouring the ``on_delete`` of everything pointing at it.

    ``restrict`` is checked for *every* referrer before anything is mutated:
    a delete that nulls two references and then refuses on a third would leave
    the caller's data changed by an operation that reported failure.

    ``_visited`` guards the ``cascade`` recursion. A user-defined graph can
    hold a cycle — two types each relating to the other — and without it the
    first such cycle is a ``RecursionError`` in a delete handler.
    """
    visited = _visited if _visited is not None else set()
    if record.id in visited:
        return
    visited.add(record.id)

    refs = await _relations.referrers(db, record)
    blocked = [ref for ref in refs if ref.on_delete == _RESTRICT]
    if blocked:
        raise ReferencedByOthers(
            f"{len(blocked)} record(s) still reference {record.uuid}",
            [ref.record.uuid for ref in blocked],
        )
    for ref in refs:
        if ref.on_delete == _SET_NULL:
            await _apply_set_null(db, ref, record.uuid)
        elif ref.on_delete == _CASCADE:
            await soft_delete_record(
                db, ref.rtype, ref.record, actor=actor, settings=settings, _visited=visited
            )

    record.is_deleted = True
    record.deleted_at = utcnow()
    record.deleted_by = actor
    db.add(record)
    await db.flush()
    await write_revision(
        db, record, RevisionEvent.DELETE, limit=settings.revision_limit, actor=actor
    )


async def restore_record(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    *,
    settings: RecordsSettings,
    actor: str | None = None,
) -> Record:
    """Bring a record back, and rebuild its index rows.

    The rebuild is not redundant with §7.3's "index rows survive a soft
    delete": the schema may have moved while the row sat in the trash, and the
    index is supposed to reflect the *current* schema (§8.3). Reindexing one
    record is cheap and it is the difference between a restore that is
    queryable and one that is merely visible.
    """
    record.is_deleted = False
    record.deleted_at = None
    record.deleted_by = None
    record.updated_by = actor
    db.add(record)
    await db.flush()
    await write_revision(
        db, record, RevisionEvent.RESTORE, limit=settings.revision_limit, actor=actor
    )
    await reindex_record(db, record, rtype, resolve_type_id=await type_resolver(db))
    return record


async def _purge(db: AsyncSession, records: list[Record]) -> None:
    """Really delete rows, by core statement, and detach what is left holding them.

    ``session.delete()`` cannot do this: the framework's ``before_flush``
    listener intercepts the delete of any ``SoftDeleteMixin`` row, expunges it
    and re-adds it with ``is_deleted = True`` (``simple_module_db.listeners``).
    That is the right default and it makes a hard delete unexpressible through
    the ORM — so a purge is a core ``DELETE``, the identity map is cleared by
    hand because a core statement does not touch it, and the session is marked
    written because core DML does not fire ``after_flush``.

    Revisions are deleted explicitly although the FK says ``ON DELETE
    CASCADE``: SQLite does not enforce foreign keys unless
    ``PRAGMA foreign_keys`` is on, and it is not here, so relying on the
    cascade would leave orphaned revision rows on the default dev backend and
    not on Postgres.
    """
    ids = [record.id for record in records if record.id is not None]
    if not ids:
        return
    await db.execute(sa_delete(RecordRevision).where(RecordRevision.record_id.in_(ids)))
    await db.execute(sa_delete(Record).where(Record.id.in_(ids)))
    await db.flush()
    for record in records:
        db.expunge(record)
    mark_written(db)


async def hard_delete_record(db: AsyncSession, rtype: RecordType, record: Record) -> None:
    """Purge a trashed record, index rows and all.

    Only a record already in the trash: a purge is unrecoverable, and making
    it reachable in one step from a live record turns a mis-click into
    permanent data loss.
    """
    if not record.is_deleted:
        raise Conflict(f"record {record.uuid} must be in the trash before it can be purged")
    await delete_index(db, record.id)
    await _purge(db, [record])


async def purge_type_records(db: AsyncSession, rtype: RecordType) -> int:
    """Hard-delete every record of a type, trashed or live. Returns the count.

    Deleting a type is the one operation that purges live records, so it
    cannot go through :func:`hard_delete_record` — which refuses anything not
    already in the trash, on purpose.
    """
    stmt = select(Record).where(Record.type_id == rtype.id).execution_options(include_deleted=True)
    records = list((await db.execute(stmt)).scalars().all())
    for record in records:
        await delete_index(db, record.id)
    await _purge(db, records)
    return len(records)
