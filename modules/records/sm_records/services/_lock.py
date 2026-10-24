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

from collections.abc import Iterable
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import RecordType
from sm_records.services.errors import Conflict
from sm_records.tenancy import bound_tenant

__all__ = ["lock_type", "lock_types"]

_HELD = "sm_records.type_locks"
"""``Session.info`` key: ``(root transaction, ids locked in it)`` — see :func:`lock_types`."""


class Locked(Protocol):
    """What a lock needs to know of a type: its id, its key for the message,
    and the collection the caller has been reading it from."""

    @property
    def id(self) -> Any: ...
    @property
    def key(self) -> str: ...
    @property
    def collection(self) -> str | None: ...


def _held(db: AsyncSession) -> set[int]:
    """The type ids already locked by this session's current transaction.

    Keyed on the root transaction object, so a commit — the reindex runner
    commits per batch and locks again — starts an empty set rather than
    inheriting one whose locks were released.
    """
    txn = db.sync_session.get_transaction()
    entry = db.info.get(_HELD)
    if entry is None or entry[0] is not txn:
        entry = (txn, set())
        db.info[_HELD] = entry
    return entry[1]


_LOCK_NOT_AVAILABLE = "55P03"
"""Postgres' SQLSTATE for a ``NOWAIT`` lock somebody else holds."""


async def _lock_one(
    db: AsyncSession, rtype: Locked, *, nowait: bool = False, schema_version: int | None = None
) -> None:
    if db.get_bind().dialect.name == "sqlite":
        # The tenant said explicitly: this is DML, which no tenant filter
        # reaches (tenancy design §E).
        # ``RETURNING`` reads the collection in the same statement, so the
        # re-read costs no round trip on the path every write takes.
        found = (
            await db.execute(
                sa_update(RecordType)
                .where(RecordType.id == rtype.id, RecordType.tenant_id == bound_tenant())
                .values(version=RecordType.version, updated_at=RecordType.updated_at)
                .returning(RecordType.id, RecordType.collection, RecordType.schema_version)
            )
        ).first()
    else:
        stmt = (
            select(RecordType.id, RecordType.collection, RecordType.schema_version)
            .where(RecordType.id == rtype.id)
            .with_for_update(nowait=nowait)
        )
        try:
            found = (await db.execute(stmt)).first()
        except DBAPIError as exc:
            code = getattr(exc.orig, "pgcode", None) or getattr(exc.orig, "sqlstate", None)
            if not nowait or code != _LOCK_NOT_AVAILABLE:
                raise
            raise Conflict(
                f"record type {rtype.key!r} is being written by another request; "
                "nothing was written — send the request again"
            ) from exc
    if found is None:
        raise Conflict(
            f"record type {rtype.key!r} was deleted while this write was waiting for it; "
            "nothing was written"
        )
    if found[1] != rtype.collection:
        raise Conflict(
            f"record type {rtype.key!r} moved to another collection while this write "
            "was waiting for it; nothing was written — send the request again"
        )
    if schema_version is not None and found[2] != schema_version:
        raise Conflict(
            f"the schema of record type {rtype.key!r} changed while this write was "
            "waiting for it; nothing was written — reload and send the request again"
        )


async def lock_types(
    db: AsyncSession, rtypes: Iterable[Locked], *, schema_versions: dict[int, int] | None = None
) -> None:
    """Lock several types, **in ascending id order**, re-reading each one's
    ``collection`` — the one locking protocol of this module (#82).

    Every write to a type's rows — a record write, a trash, restore or purge,
    an empty-trash, a move, a schema change — takes that type's lock *before*
    its first row write, and an operation that writes the rows of several
    types (a delete cascading through the relation graph) takes all of them
    up front, through here. Two consequences, and both are the point:

    * **No row lock is ever waited for while a type lock is held by someone
      else's writer of those rows**, because nobody writes a row without the
      type lock. A move therefore needs no row locks of its own: it holds its
      type's lock and every writer of those rows is queued behind it.
    * **No transaction waits for a type lock out of order.** Locks are taken
      in ascending id order; a transaction already holding a higher id that
      needs a lower one — a seed reset deleting types newest first, or a
      relation graph changing under a running delete — takes it with
      ``NOWAIT`` on Postgres, and a lock somebody else holds is a retryable
      ``409`` rather than a wait. A waiter therefore only ever waits for a
      higher id than any it holds, which is what rules a cycle out. SQLite
      needs neither: its lock is the database's one write lock, and the
      first ``lock_types`` of a transaction already holds it.
    """
    wanted = {int(rtype.id): rtype for rtype in rtypes}
    held = _held(db)
    ceiling = max(held, default=None)
    for type_id in sorted(wanted):
        late = ceiling is not None and type_id < ceiling and type_id not in held
        expected = (schema_versions or {}).get(type_id)
        await _lock_one(db, wanted[type_id], nowait=late, schema_version=expected)
        # Read again after the statement: the first lock of a transaction is
        # what begins it, so the set has to be the new transaction's.
        _held(db).add(type_id)


async def lock_type(
    db: AsyncSession, rtype: RecordType, *, schema_version: int | None = None
) -> None:
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

    **The lock also re-reads ``collection``** (#82). A writer loads its type
    row *before* it reaches this lock, and a collection move commits while it
    waits here — so without the re-read the writer would go on to write into
    the table set the type just left, a record no read could ever find. The
    value read once the lock is held is the committed one (``FOR UPDATE``
    returns the latest row version on Postgres; on SQLite the write lock is
    exclusive, and a snapshot older than the move cannot take it at all), and
    a disagreement is a ``409`` the caller can simply retry.

    **A record write also passes the ``schema_version`` it validated against**
    (#101): it validates before it takes the lock, so a schema change that
    commits in between — a type made a newsletter, whose required ``sm_email``
    the payload never had — would otherwise be written past. A mismatch is the
    same retryable ``409``.
    """
    versions = None if schema_version is None else {int(rtype.id): schema_version}
    await lock_types(db, [rtype], schema_versions=versions)
