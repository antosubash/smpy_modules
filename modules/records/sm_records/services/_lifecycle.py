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

from sm_records.index.reindex import reindex_record
from sm_records.index.writer import delete_index, write_index
from sm_records.models import Record, RecordRevision, RecordType, RevisionEvent
from sm_records.services import _payload, _relations
from sm_records.services._common import (
    guarded_bump,
    mark_written,
    reload,
    type_resolver,
    utcnow,
)
from sm_records.services.errors import Conflict, ReferencedByOthers
from sm_records.services.revisions import write_revision
from sm_records.settings import RecordsSettings

_RESTRICT = "restrict"
_SET_NULL = "set_null"
_CASCADE = "cascade"


async def _apply_set_null(
    db: AsyncSession,
    ref: _relations.Referrer,
    uuid: str,
    *,
    actor: str | None,
    settings: RecordsSettings,
) -> None:
    """Drop the reference, then rewrite the referrer as any other edit would.

    A to-many field loses only the entry that pointed at the deleted record;
    a to-one field goes to ``None``. Nulling the whole list would delete
    references to records nobody asked to delete, which is the mistake
    ``restrict``-by-default exists to avoid one level up.

    The rewrite goes through the same bump-and-revise path
    :func:`~sm_records.services.records.update_record` uses, and not a bare
    ``data`` assignment: this *is* an edit of somebody else's record. Without
    the version bump a client holding the pre-delete version writes straight
    over it under optimistic concurrency that reports no conflict; without the
    revision the change is absent from the history panel that is supposed to
    explain where the reference went; and without recomputing
    ``display_title`` a type whose ``display_field`` *is* the relation keeps a
    list-screen title naming a record that is now in the trash.
    """
    data = dict(ref.record.data or {})
    value = data.get(ref.field_key)
    if isinstance(value, list):
        kept = [item for item in value if not (isinstance(item, dict) and item.get("uuid") == uuid)]
        data[ref.field_key] = kept or None
    else:
        data[ref.field_key] = None

    expected = ref.record.version
    if not await guarded_bump(db, Record, ref.record.id, expected):
        raise Conflict(
            f"record {ref.record.uuid} has changed since it was read",
            current=await reload(db, Record, ref.record.id),
        )
    ref.record.data = data
    ref.record.version = expected + 1
    ref.record.updated_by = actor
    # The stored payload, not a revalidated one: the referrer may be stamped at
    # an older ``schema_version`` than its type now carries (§8.3), and a
    # delete elsewhere is not the event that gets to refuse it.
    ref.record.display_title = _payload.display_title(ref.rtype, data)
    db.add(ref.record)
    await db.flush()
    await write_revision(
        db, ref.record, RevisionEvent.UPDATE, limit=settings.revision_limit, actor=actor
    )
    await write_index(db, ref.record, ref.rtype, resolve_type_id=await type_resolver(db))


def _role_blocked(rtype: RecordType, roles: Sequence[str] | None) -> bool:
    """Design §10's ``allowed_roles`` narrowing, for a type the caller never named.

    ``deps.check_type_roles`` only ever sees the type in the URL, so a cascade
    or a set_null into a *different* type used to trash or rewrite records the
    caller is not allowed to write at all — the narrowing was one relation
    field away from being decorative. ``roles is None`` means "no caller":
    the CLI and any system path keep the unrestricted behaviour.
    """
    if roles is None:
        return False
    allowed = rtype.allowed_roles or []
    return bool(allowed) and not set(roles).intersection(allowed)


async def _plan_delete(
    db: AsyncSession, rtype: RecordType, record: Record, roles: Sequence[str] | None
) -> tuple[list[tuple[Record, RecordType]], list[tuple[_relations.Referrer, str]], list[str]]:
    """Walk the whole referrer graph without touching a row.

    Returns ``(records to trash, set_null rewrites, restrict blockers)``. The
    walk is breadth-first with a visited set, because a user-defined graph can
    hold a cycle — two types each relating to the other — and without the set
    the first such cycle is a ``RecursionError`` in a delete handler.
    """
    trash: list[tuple[Record, RecordType]] = [(record, rtype)]
    set_nulls: list[tuple[_relations.Referrer, str]] = []
    blockers: list[str] = []
    seen_blockers: set[str] = set()
    visited: set[int] = {record.id}
    queue: list[Record] = [record]

    while queue:
        current = queue.pop(0)
        for ref in await _relations.referrers(db, current):
            behaviour = ref.on_delete
            if behaviour != _RESTRICT and _role_blocked(ref.rtype, roles):
                behaviour = _RESTRICT
            if behaviour == _RESTRICT:
                if ref.record.uuid not in seen_blockers:
                    seen_blockers.add(ref.record.uuid)
                    blockers.append(ref.record.uuid)
            elif behaviour == _SET_NULL:
                set_nulls.append((ref, current.uuid))
            elif behaviour == _CASCADE and ref.record.id not in visited:
                visited.add(ref.record.id)
                trash.append((ref.record, ref.rtype))
                queue.append(ref.record)
    return trash, set_nulls, blockers


async def _trash(
    db: AsyncSession, record: Record, *, actor: str | None, settings: RecordsSettings
) -> None:
    record.is_deleted = True
    record.deleted_at = utcnow()
    record.deleted_by = actor
    db.add(record)
    await db.flush()
    await write_revision(
        db, record, RevisionEvent.DELETE, limit=settings.revision_limit, actor=actor
    )


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
    :func:`_role_blocked`.
    """
    trash, set_nulls, blockers = await _plan_delete(db, rtype, record, roles)
    if blockers:
        raise ReferencedByOthers(
            f"{len(blockers)} record(s) still reference {record.uuid}", blockers
        )
    for ref, target_uuid in set_nulls:
        await _apply_set_null(db, ref, target_uuid, actor=actor, settings=settings)
    for doomed, _ in trash:
        await _trash(db, doomed, actor=actor, settings=settings)


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
