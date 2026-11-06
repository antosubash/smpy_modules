"""One subscriber's row, locked to the end of the transaction (newsletter PR 6, C2).

Every unsubscribe (:func:`.opt_in.leave`, so the contract's ``unsubscribe``,
records' own link and newsletter's unsubscribe page) and the contract's
``lock_confirmation`` take it before they decide, so a decision read from the
row stays true until the transaction that made it ends: an opt-out cannot
land between newsletter's "confirmed after the opt-out?" check and its lift.

Before it, :func:`.opt_in.leave` takes the address's opt-out lock
(:mod:`.address_lock`), as newsletter's import batch does for each of its
addresses before its type lock. The type lock comes next, as everywhere in records
(``services._lock.lock_types``): nobody waits for a row lock while holding a
type lock someone else's writer of that row needs, and an unsubscribe's
``update_record`` takes the type lock anyway. Then the row:

* Postgres: ``SELECT … FOR UPDATE`` of the row;
* SQLite: the type lock is a write (``RESERVED``), which is already the
  database's one write lock for the rest of the transaction, so the plain
  reload that follows cannot be raced by another writer.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import Record, RecordType
from sm_records.records.services._lock import lock_type

__all__ = ["lock_record"]


async def lock_record(db: AsyncSession, rtype: RecordType, record: Record) -> Record:
    """``record`` reloaded into the same instance (trashed included) under a
    lock held until this transaction ends."""
    await lock_type(db, rtype)
    cls = type(record)
    stmt = (
        select(cls)
        .where(cls.id == record.id, cls.tenant_id == record.tenant_id)
        .execution_options(include_deleted=True, populate_existing=True)
    )
    if db.get_bind().dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalars().one()
