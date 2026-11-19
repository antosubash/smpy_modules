"""Purging records for good: one record, or a whole type.

Split out of :mod:`sm_records.records.services.delete._lifecycle` for the file cap (a moves-only
change: the bodies are as they were). ``_lifecycle`` re-exports both names, so callers still import
one module. Everything here is irrevocable, which is why both go through the same locks and
``_purge_ids``/``forget_deliveries`` discipline.
"""

from __future__ import annotations

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.core import events
from sm_records.core.tenancy import bound_tenant
from sm_records.models import Record, RecordType, tables_for
from sm_records.records.index._reduce_write import drop_type_rows
from sm_records.records.services._common import PurgedRecord, mark_written
from sm_records.records.services._lock import lock_type
from sm_records.records.services.delete._delete_locks import still_there
from sm_records.records.services.delete._empty_trash import _purge_ids
from sm_records.records.services.delete._forget_deliveries import forget_deliveries

__all__ = ["hard_delete_record", "purge_type_records"]


async def hard_delete_record(db: AsyncSession, rtype: RecordType, record: Record) -> None:
    """Purge a trashed record, index rows and all.

    Only a record already in the trash: a purge is unrecoverable, and making
    it reachable in one step from a live record turns a mis-click into
    permanent data loss.
    """
    await lock_type(db, rtype)
    await still_there(
        db,
        rtype,
        record,
        trashed=True,
        refusal=f"record {record.uuid} must be in the trash before it can be purged",
    )
    # Built before the purge: afterwards the row is expunged and the uuid it
    # names is the one thing a subscriber cannot look up any more.
    purged = events.purged(rtype, record)
    # **No reduce delta**: the record was decremented when it was trashed, and
    # the refusal above guarantees only a trashed record reaches here, so a
    # second decrement would take the group below the truth (Phase 5 §5.2).
    await _purge_ids(db, rtype, [record.id])
    # A core statement does not touch the identity map, so the instance still
    # holding the deleted row is detached by hand.
    db.expunge(record)
    events.emit(db, purged)


async def purge_type_records(db: AsyncSession, rtype: RecordType) -> list[PurgedRecord]:
    """Hard-delete every record of a type, trashed or live — **set-based**.

    Deleting a type is the one operation that purges live records, so it
    cannot go through :func:`hard_delete_record`, which refuses anything not
    already in the trash on purpose.

    **Ten statements, not ten per record.** This used to load every record as
    an ORM instance, call :func:`delete_index` per record (six ``DELETE``s
    each, by ``record_id``) and then delete the documents by a ten-thousand-
    element ``IN`` list: deleting a 10,000-record type took 101 s inside one
    HTTP request, past any reverse proxy's read timeout, at which point the
    client sees a 504 while the server keeps deleting. Every index table
    carries ``type_id`` — it is the discriminator the whole index design is
    built on — so one ``DELETE ... WHERE type_id = :id`` per table says the
    same thing, and the documents and revisions go the same way.

    **What is still read is the three columns the events need.** A
    ``RecordPurged`` is the one event a subscriber cannot recover by
    re-reading, so it has to carry what the row held; it carries ``uuid``,
    ``locale`` and ``translation_group`` and nothing else, as a column
    select rather than as ORM instances. That is one cheap statement for the
    whole type instead of ten thousand instantiations, and the docs say that
    a purge event carries identity rather than payload.

    Order matters: the revision delete reads the document table, so it has to
    run before the documents go.
    """
    tables = tables_for(rtype)
    cls = tables.record
    purged = list(
        (
            await db.execute(
                select(cls.uuid, cls.locale, cls.translation_group)
                .where(cls.type_id == rtype.id)
                .execution_options(include_deleted=True)
            )
        ).all()
    )
    for table in tables.index_tables:
        await db.execute(sa_delete(table).where(table.type_id == rtype.id))
    # One statement rather than a delta per live record: the type is going
    # away, so every group of every spec on it goes with it. A reduce row has
    # no foreign key to cascade through, so this is what removes them.
    await drop_type_rows(db, rtype.id)
    # Explicit rather than via the FK's ON DELETE CASCADE, for the reason
    # ``_empty_trash._purge_ids`` gives: SQLite leaves foreign keys unenforced unless the
    # pragma is on, so the cascade would clean up on Postgres and orphan rows
    # on the default dev backend.
    #
    # The tenant on both DELETEs *and* inside the ``IN`` subquery: DML and a
    # mapper inside ``in_()`` are the shapes no tenant filter reaches
    # (tenancy design §E, FACT 1d/1e).
    tenant = bound_tenant()
    owned = select(cls.id).where(cls.type_id == rtype.id, cls.tenant_id == tenant)
    await db.execute(
        sa_delete(tables.revision).where(
            tables.revision.record_id.in_(owned), tables.revision.tenant_id == tenant
        )
    )
    uuids = select(cls.uuid).where(cls.type_id == rtype.id, cls.tenant_id == tenant)
    await forget_deliveries(db, tenant, uuids, lock=cls.type_id == rtype.id, table=cls)
    await db.execute(sa_delete(cls).where(cls.type_id == rtype.id, cls.tenant_id == tenant))
    await db.flush()
    # Core DML does not fire ``after_flush``, so the request's session would
    # otherwise take ``get_db``'s read-only branch and never commit the purge.
    mark_written(db)
    return purged
