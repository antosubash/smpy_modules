"""The delete lifecycle: trash, restore, purge — and what relations cost.

Split out of :mod:`sm_records.services.records` for the file cap, and it is
the natural seam: everything here is about a record's *existence* rather than
its content, and all of it turns on design §9's rule that ``on_delete`` is a
property of the referring field, enforced in the service because there is no
foreign key to enforce it in the database. ``records`` re-exports these, so
callers still import one module.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index._reduce_write import apply_delta, drop_type_rows
from sm_records.index.reindex import reindex_record
from sm_records.index.writer import delete_index
from sm_records.models import Record, RecordType, RevisionEvent, TableSet, tables_for
from sm_records.services._common import mark_written, type_resolver, utcnow

# Split out for the file cap: everything about the referrer graph — walking
# it, and rewriting the records that point at the one being deleted — lives
# there, and everything about a record's own existence lives here.
from sm_records.services._delete_plan import apply_set_null, plan_delete
from sm_records.services.errors import Conflict, ReferencedByOthers
from sm_records.services.revisions import write_revision
from sm_records.settings import RecordsSettings


async def _trash(
    db: AsyncSession,
    record: Record,
    rtype: RecordType,
    *,
    actor: str | None,
    settings: RecordsSettings,
) -> None:
    """Trash one record and take it out of every maintained aggregate.

    The map index rows stay (§7.3: every query joins back to the record row,
    where the framework's filter hides it). A reduce row has no record to join
    back to, so a trashed record left counted would be counted forever — hence
    the decrement, and the matching increment in :func:`restore_record`.
    ``rtype`` is threaded in for that: a cascade trashes records of types the
    URL never named, each folding under its own type's specs."""
    now = utcnow()
    record.is_deleted = True
    record.deleted_at = now
    record.deleted_by = actor
    db.add(record)
    await db.flush()
    await write_revision(
        db, record, RevisionEvent.DELETE, limit=settings.revision_limit, actor=actor
    )
    await apply_delta(db, rtype, before=record, after=None, now=now)


async def soft_delete_record(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    *,
    actor: str | None = None,
    settings: RecordsSettings,
    roles: Sequence[str] | None = None,
) -> None:
    """Trash a record, honouring the ``on_delete`` of everything pointing at it.

    Plan, then apply. The whole referrer graph is walked first and *every*
    ``restrict`` in it collected — not only the ones one level down — before a
    single row is touched. Checking level by level meant a delete could null a
    ``set_null`` referrer, cascade into a second type, and only then meet a
    ``restrict`` it had to refuse: the caller got a 409 for an operation that
    had already rewritten their data, and (until the endpoint layer learned to
    roll back) committed it.

    ``roles`` is the caller's role list, and ``None`` means unrestricted —
    the CLI, a background task, any path with no user behind it. Given a list,
    a referrer whose *type* narrows writes to roles the caller does not hold
    is treated as ``restrict`` however its field is declared: see
    :func:`~sm_records.services._common.role_blocked`.
    """
    trash, set_nulls, blockers = await plan_delete(db, rtype, record, roles)
    if blockers:
        raise ReferencedByOthers(
            f"{len(blockers)} record(s) still reference {record.uuid}", blockers
        )
    for ref, target_uuid in set_nulls:
        await apply_set_null(db, ref, target_uuid, actor=actor, settings=settings)
    for doomed, doomed_type in trash:
        await _trash(db, doomed, doomed_type, actor=actor, settings=settings)


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
    # No ``previous``: a trashed record is not counted, so to a reduce index a
    # restore is an *arrival* — +1, the mirror of ``_trash``'s decrement.
    await reindex_record(db, record, rtype, resolve_type_id=await type_resolver(db))
    return record


async def _purge(db: AsyncSession, tables: TableSet, records: list[Record]) -> None:
    """Really delete rows of one table set, by core statement, and detach what
    is left holding them.

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
    await db.execute(sa_delete(tables.revision).where(tables.revision.record_id.in_(ids)))
    await db.execute(sa_delete(tables.record).where(tables.record.id.in_(ids)))
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
    # **No reduce delta**: the record was decremented when it was trashed, and
    # the refusal above guarantees only a trashed record reaches here, so a
    # second decrement would take the group below the truth (Phase 5 §5.2).
    tables = tables_for(rtype)
    await delete_index(db, tables, record.id)
    await _purge(db, tables, [record])


async def purge_type_records(db: AsyncSession, rtype: RecordType) -> int:
    """Hard-delete every record of a type, trashed or live. Returns the count.

    Deleting a type is the one operation that purges live records, so it
    cannot go through :func:`hard_delete_record` — which refuses anything not
    already in the trash, on purpose.
    """
    tables = tables_for(rtype)
    cls = tables.record
    stmt = select(cls).where(cls.type_id == rtype.id).execution_options(include_deleted=True)
    records = list((await db.execute(stmt)).scalars().all())
    for record in records:
        await delete_index(db, tables, record.id)
    # One statement rather than a delta per live record: the type is going
    # away, so every group of every spec on it goes with it. A reduce row has
    # no foreign key to cascade through, so this is what removes them.
    await drop_type_rows(db, rtype.id)
    await _purge(db, tables, records)
    return len(records)
