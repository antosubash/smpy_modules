"""Moving a populated type between collections (#82).

``PUT /types/{key}`` with a changed ``collection`` copies the type's records,
revisions and index rows into the target table set and deletes them from the
source, inside the request's one transaction. Split from
:mod:`sm_records.services._type_update` for the 300-line cap.

**What has to move, and what does not.** A collection holds a type's
``record``, ``revision`` and six index tables (Phase 5 §6.1), and those are
what is copied. Everything that *refers* to the type's records names them by
something the move leaves alone:

* **Relations into the type** live in the *referrer's* ``index_ref`` rows and
  name their target by ``(target_uuid, target_type_id)`` — both unchanged, and
  ``?expand=``, the referrers listing and the delete walk all find the target's
  table through ``tables_for(target_type)``, which follows the new
  ``collection`` the moment the type row says so. Nothing to re-point.
* **The type's own outbound references** are ``index_ref`` rows in its own
  set, so they are copied like every other index row.
* **The reduce table, the type revisions, settings, permissions** are global
  (§6.4) and keyed by ``type_id``, which does not change. Public API paths and
  events address records by ``(type_key, uuid)``, which do not change either.

What *does* change is every row id, because two table sets number their rows
independently. Nothing outside the moved rows stores one, with one caveat
documented in the README: an ``?after=`` cursor taken before the move encodes
an old id, and pages from the wrong place once.

**Set-based, never per record**: one ``INSERT … SELECT`` per index table and
keyset batches of :data:`MOVE_BATCH` for the two tenant-owned tables (see
:func:`_copy_batched`), the id mapping made by joining the two record tables
on ``(tenant_id, uuid)`` — unique per tenant across every table set — then
one ``DELETE`` per table. Core statements over ``__table__`` are invisible to the
tenancy guard (``_tenant_guard``) and, before framework 0.0.37, to the framework's
tenant criteria too, so every one of them carries an explicit
``tenant_id`` predicate (tenancy design §E); the index tables carry no tenant
column and are reached only through a tenant-scoped record id.

**One transaction is the rollback story.** Nothing commits until the request
does; a failure anywhere is a rollback that leaves the source set as it was.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, and_, delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.collections import collections
from sm_records.contracts.events import RecordTypeMoved
from sm_records.models import RecordType, table_set, tables_for
from sm_records.services._claims import lock_type
from sm_records.services._common import mark_written
from sm_records.services.errors import Conflict, ValidationFailed

__all__ = ["check_target", "move_type"]

_ALL_ROWS = {"include_deleted": True}
"""Every statement here reads the trash too: a trashed record moves with its type.

The DML and ``INSERT … SELECT`` sources need it as much as the reads: since
framework 0.0.37 the soft-delete criteria reach Core statements on
``Model.__table__``, subqueries included."""

MOVE_BATCH = 500
"""Rows per insert when copying a tenant-owned table (see :func:`_copy_batched`)."""


def check_target(target: str | None) -> None:
    """The collection named must be one this process declares — the same
    ``422`` ``POST /types`` answers, since it is the same mistake."""
    if target is None or target in collections():
        return
    named = ", ".join(collections()) or "none — this host declares no collections"
    raise ValidationFailed(
        f"collection {target!r} is not declared by this host (declared: {named})",
        [{"field": "collection", "message": f"{target!r} is not a declared collection"}],
    )


def _copy_columns(table: Any, *skip: str) -> list[str]:
    return [column.name for column in table.columns if column.name not in {"id", *skip}]


async def _copy_batched(db: AsyncSession, rows: Select, order: Any, to_table: Any) -> None:
    """Insert ``rows`` into ``to_table``, ``MOVE_BATCH`` at a time by ``order``.

    The tenant-owned tables (records, revisions) cannot take an
    ``INSERT … SELECT``: the framework's insert guard stamps ``tenant_id`` onto
    every insert into one and has no form for a select-fed one. Rows carrying
    their own ``tenant_id`` as parameters are what it checks instead — against
    the bound tenant, so a foreign row could not be written even by mistake.
    Keyset batches keep memory flat for a large type.
    """
    last: Any = None
    while True:
        page = rows.add_columns(order.label("_move_key")).order_by(order).limit(MOVE_BATCH)
        if last is not None:
            page = page.where(order > last)
        batch = (await db.execute(page, execution_options=_ALL_ROWS)).mappings().all()
        if not batch:
            return
        await db.execute(
            insert(to_table),
            [{key: value for key, value in row.items() if key != "_move_key"} for row in batch],
        )
        last = batch[-1]["_move_key"]


async def move_type(db: AsyncSession, rtype: RecordType, target: str | None) -> int:
    """Move every record of ``rtype`` (trash included) to ``target``'s
    tables; return how many moved. The caller writes ``collection`` onto the
    type row afterwards, in the same transaction.

    Refused with a ``409``, before a row is written, when the type has a
    reindex outstanding — the runner is walking the *source* index tables —
    or when a uuid of the type is already in the target set, which the
    per-tenant uuid rule makes impossible for rows this module wrote and
    which would otherwise surface as an ``IntegrityError``.
    """
    await lock_type(db, rtype)
    # Read under the lock, not off the instance: ``cli reindex`` marks a type
    # pending without bumping its version, so the caller's row can be stale.
    pending = await db.scalar(select(RecordType.reindex_pending).where(RecordType.id == rtype.id))
    if pending:
        raise Conflict(
            f"type {rtype.key!r} has a reindex outstanding; move it once the reindex finishes"
        )
    source, dest = tables_for(rtype), table_set(target)
    src, dst = source.record.__table__, dest.record.__table__
    tenant = rtype.tenant_id
    mine = and_(src.c.type_id == rtype.id, src.c.tenant_id == tenant)
    # No row locks: every writer of this type's rows — a record write, a
    # trash, restore, purge or empty-trash, a cascade or ``set_null`` reaching
    # in from another type — holds this type's lock before its first row write
    # (``services._lock.lock_types``), so all of them are queued behind the
    # lock just taken, and the copy below reads rows nobody else can change.
    clash = await db.scalar(
        select(func.count())
        .select_from(dst)
        .where(dst.c.tenant_id == tenant, dst.c.uuid.in_(select(src.c.uuid).where(mine))),
        execution_options=_ALL_ROWS,
    )
    if clash:
        raise Conflict(
            f"{clash} record(s) of {rtype.key!r} share a uuid with a record already in "
            f"{target or 'the shared tables'!r}; nothing was moved"
        )

    moved = (
        await db.scalar(
            select(func.count()).select_from(src).where(mine), execution_options=_ALL_ROWS
        )
        or 0
    )
    if moved:
        await _copy_rows(db, rtype, source, dest, mine)
    mark_written(db)
    # An empty type moves too — its ``collection`` changes and commits — so it
    # publishes like any other move, with ``moved=0``.
    events.emit(
        db,
        RecordTypeMoved(
            type_key=rtype.key,
            tenant_id=tenant,
            source=source.name,
            target=dest.name,
            moved=moved,
        ),
    )
    return moved


async def _copy_rows(
    db: AsyncSession, rtype: RecordType, source: Any, dest: Any, mine: Any
) -> None:
    """Copy every row of the type into ``dest``, then delete it from ``source``."""
    src, dst = source.record.__table__, dest.record.__table__
    columns = _copy_columns(src)
    await _copy_batched(db, select(*[src.c[n] for n in columns]).where(mine), src.c.id, dst)

    # old id -> new id, by the uuid both rows carry.
    pairs = (
        select(src.c.id.label("old_id"), dst.c.id.label("new_id"))
        .join(
            dst,
            and_(
                dst.c.uuid == src.c.uuid,
                dst.c.tenant_id == src.c.tenant_id,
                dst.c.type_id == rtype.id,
            ),
        )
        .where(mine)
        .subquery()
    )
    children = [
        (source.revision, dest.revision),
        *zip(source.index_tables, dest.index_tables, strict=True),
    ]
    for from_cls, to_cls in children:
        from_table, to_table = from_cls.__table__, to_cls.__table__
        names = _copy_columns(from_table, "record_id")
        rows = select(*[from_table.c[n] for n in names], pairs.c.new_id.label("record_id")).join(
            pairs, pairs.c.old_id == from_table.c.record_id
        )
        if "tenant_id" in from_table.c:
            await _copy_batched(db, rows, from_table.c.id, to_table)
        else:
            # No tenant column, so nothing for the framework's insert guard to
            # stamp: one ``INSERT … SELECT``, scoped through ``pairs``.
            await db.execute(
                insert(to_table).from_select([*names, "record_id"], rows),
                execution_options=_ALL_ROWS,
            )

    old_ids = select(src.c.id).where(mine)
    for from_cls, _ in children:
        from_table = from_cls.__table__
        await db.execute(
            delete(from_table).where(from_table.c.record_id.in_(old_ids)),
            execution_options=_ALL_ROWS,
        )
    await db.execute(delete(src).where(mine), execution_options=_ALL_ROWS)
