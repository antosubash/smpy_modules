"""Serialising the writers of one record type — the lock, and only the lock.

Split from :mod:`sm_records.services._claims` for the 300-line cap, and the
seam is a real one: that module is *what a write claims about the rest of the
type* (a slug nobody else holds, a ``unique`` value nobody else holds), and
this is the dialect-specific primitive that makes a check-then-act claim hold
at all. It is the one thing in that pair with no opinion about records —
``schema_change`` and the reindex runner take it too, for writes that touch no
payload.

Re-exported from ``_claims``, so every caller keeps importing one module.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import RecordType
from sm_records.tenancy import bound_tenant

__all__ = ["lock_type"]


async def lock_type(db: AsyncSession, rtype: RecordType) -> None:
    """Serialise writes of one type — the mitigation design §7.8 names.

    The ``unique`` check is check-then-act, so two concurrent creates carrying
    the same value can both pass it. Taking the type row first makes the
    window empty: the second writer waits for the first to commit and then
    sees its index row.

    **Two statements, because a lock is a dialect feature and not a grammar
    one.** ``SELECT ... FOR UPDATE`` is the row lock on Postgres; on SQLite it
    compiles to a plain ``SELECT`` that locks nothing, and the reasoning that
    "the database is single-writer anyway" is where this went wrong. SQLite is
    single-*writer*, not single-*transaction*: a read-only transaction takes no
    lock at all, so eight concurrent creates each ran the check, each found the
    value free, and each then took the write lock in turn to insert. Eight
    201s, eight rows — measured. Issuing a write against the type row instead
    takes SQLite's ``RESERVED`` lock **at the top of the write path**, and
    ``RESERVED`` is exclusive among writers for the rest of the transaction, so
    the second writer blocks here rather than at its own ``INSERT`` — which is
    after its check. ``SET version = version`` is deliberately a no-op
    assignment: it must not bump the value any optimistic-concurrency caller is
    comparing against, and it must still be a write.

    ``updated_at`` is held to its own value for the same reason: a lock is not
    an edit, and ``AuditMixin``'s ``onupdate=func.now()`` fires on any
    ``UPDATE`` not naming the column — moving the row's "last changed" and
    leaving the attribute expired, the trap ``_common.guarded_bump`` documents.

    This serialises every write to the type on SQLite, which is the trade §7.8
    describes and the README states. It is taken for every write rather than
    only for types with a ``unique`` field: the slug claim of §5 is the same
    check-then-act, and every type can have one.
    """
    if db.get_bind().dialect.name == "sqlite":
        # The tenant said explicitly: this is DML, which no tenant filter
        # reaches (tenancy design §E).
        await db.execute(
            sa_update(RecordType)
            .where(RecordType.id == rtype.id, RecordType.tenant_id == bound_tenant())
            .values(version=RecordType.version, updated_at=RecordType.updated_at)
        )
        return
    await db.execute(select(RecordType.id).where(RecordType.id == rtype.id).with_for_update())
