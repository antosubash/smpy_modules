"""What a lifecycle operation locks before it touches a row (#82).

:func:`sm_records.services._lock.lock_types` is the protocol — every writer of
a type's rows holds that type's lock first, and locks are taken in ascending
id order. This module answers the two questions the protocol leaves to the
caller for trash, restore and purge:

* **Which types.** A restore or a purge writes its own type's rows and
  nothing else. A trash also rewrites ``set_null`` referrers and trashes
  ``cascade`` ones, of types the URL never names, so it locks the part of the
  relation graph a delete *can* reach — read from the schemas before the walk,
  since the walk itself reads rows and must run under the locks. A plan that
  then reaches a type outside that set (a relation added or retargeted while
  the delete waited) is a retryable ``409``, never a write without a lock.
* **Whether what was read before the lock still holds.** An endpoint loads its
  record before any of this runs, so once the lock is held the row is read
  again: a concurrent purge, restore or trash that committed in between is a
  ``404`` or ``409`` here, not a ``StaleDataError`` or a second
  ``RecordPurged`` for a row that is already gone.

**Referrers that are only read.** A ``restrict`` referrer is not locked — its
type is not written — but the walk reads its rows from the table set its type
is in, and a move of that type committing mid-walk would hide it. So every
type's ``collection`` is read before the walk and again after, and a change
refuses the delete with a ``409``: a move that commits after the second read
was not seen by the walk at all, and one that committed before it is caught.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import Record, RecordType, tables_for
from sm_records.schema.fields import ON_DELETE_DEFAULT
from sm_records.schema.types import FieldType
from sm_records.services._common import reload
from sm_records.services._lock import lock_types
from sm_records.services.errors import Conflict, NotFound

__all__ = ["DeleteGraph", "check_delete_plan", "lock_delete_graph", "still_there"]

_RETRY = "nothing was written — send the request again"


class _TypeRow(NamedTuple):
    id: int
    key: str
    collection: str | None


class DeleteGraph(NamedTuple):
    """The types a trash locked, and every type's collection when it did."""

    locked: frozenset[int]
    collections: dict[int, str | None]


async def _collections(db: AsyncSession) -> dict[int, str | None]:
    rows = (await db.execute(select(RecordType.id, RecordType.collection))).all()
    return {int(type_id): collection for type_id, collection in rows}


def _writers_of(rows: list[Any]) -> tuple[dict[str, set[int]], set[int]]:
    """``{target key: ids of types whose delete behaviour writes them}``, and
    the types that may write under *any* target.

    A ``restrict`` field writes nothing. A type mid-rebuild may still hold
    ``REF`` rows of a field since retargeted, still named by the field key the
    walk reads ``on_delete`` from, so a writing field on such a type counts
    for every target until the runner clears it.
    """
    by_target: dict[str, set[int]] = {}
    anywhere: set[int] = set()
    for type_id, _key, _collection, fields, pending in rows:
        for raw in fields or []:
            if raw.get("type") != FieldType.RELATION.value:
                continue
            options = raw.get("options") or {}
            if (options.get("on_delete") or ON_DELETE_DEFAULT) == "restrict":
                continue
            by_target.setdefault(str(options.get("target_type") or ""), set()).add(int(type_id))
            if pending:
                anywhere.add(int(type_id))
    return by_target, anywhere


async def lock_delete_graph(db: AsyncSession, rtype: RecordType) -> DeleteGraph:
    """Lock ``rtype`` and every type a delete of one of its records can write.

    The closure follows both ``cascade`` and ``set_null`` edges outward — a
    superset of what one walk reaches (a ``set_null`` rewrite does not
    propagate), which costs serialisation and nothing else.
    """
    rows = (
        await db.execute(
            select(
                RecordType.id,
                RecordType.key,
                RecordType.collection,
                RecordType.fields,
                RecordType.reindex_pending,
            )
        )
    ).all()
    by_id = {int(row[0]): _TypeRow(int(row[0]), str(row[1]), row[2]) for row in rows}
    by_target, anywhere = _writers_of(rows)
    reach, queue = {int(rtype.id)} | anywhere, [int(rtype.id), *anywhere]
    while queue:
        current = by_id.get(queue.pop())
        for type_id in by_target.get(current.key, ()) if current else ():
            if type_id not in reach:
                reach.add(type_id)
                queue.append(type_id)
    # The URL's own type as the caller holds it, so a move it has not seen is
    # this lock's 409; the others as just read.
    await lock_types(db, [rtype, *(by_id[i] for i in reach if i != rtype.id and i in by_id)])
    return DeleteGraph(frozenset(reach), {i: row.collection for i, row in by_id.items()})


async def check_delete_plan(
    db: AsyncSession, graph: DeleteGraph, written: list[RecordType]
) -> None:
    """Refuse a walk that wrote outside its locks or read across a move."""
    for rtype in written:
        if rtype.id not in graph.locked or rtype.collection != graph.collections.get(rtype.id):
            raise Conflict(
                f"the relations into this record changed while the delete waited ({rtype.key!r}); "
                + _RETRY
            )
    # Only types both reads saw: one created or deleted meanwhile moved nothing
    # this walk read, and a new type's writing referrer is caught just above.
    now = await _collections(db)
    if any(now.get(i, was) != was for i, was in graph.collections.items()):
        raise Conflict("a record type this delete reads moved to another collection; " + _RETRY)


async def still_there(
    db: AsyncSession, rtype: RecordType, record: Record, *, trashed: bool, refusal: str
) -> None:
    """Re-read ``record`` now the lock is held; ``refusal`` is the ``409`` when
    it is no longer on the side of the trash this operation starts from."""
    fresh = await reload(db, tables_for(rtype).record, record.id)
    if fresh is None:
        raise NotFound(f"no record {record.uuid!r} of type {rtype.key!r}")
    if bool(fresh.is_deleted) != trashed:
        raise Conflict(refusal)
