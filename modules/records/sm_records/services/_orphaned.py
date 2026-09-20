"""The reserved ``_orphaned`` sub-key, from the schema side. Design doc §8.8.

Deleting a field does not delete its values: they stay in the payload, moving
under ``_orphaned`` on the record's next write (§8.3 — lazily, never in a bulk
job that can half-fail). So adding a field back under a key some record still
carries has two wrong silent answers, and this module implements the third:

* restoring silently makes deleted content reappear unannounced;
* shadowing leaves the old values permanently unreachable and still stored;
* so the change is **refused** until the caller says ``restore`` or
  ``discard``.

Counting is done in Python over batched rows rather than as a JSON predicate:
``data`` is a plain ``JSON`` column, and the containment operators that would
push this into SQL are spelled differently on Postgres and SQLite (and index
nothing here either way). One pass over a type's records at schema-edit time is
a cost nobody notices; a query that is subtly wrong on one backend is not.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import ORPHANED_KEY
from sm_records.index.reduce_rebuild import rebuild_type
from sm_records.models import Record, RecordType
from sm_records.services._common import mark_written

RESTORE = "restore"
DISCARD = "discard"
CHOICES = (RESTORE, DISCARD)


def _payload_holds(data: dict[str, Any], key: str) -> bool:
    """Either half counts as "this record still carries a value for ``key``".

    Top level is a removed field whose value has not been migrated yet — the
    record has not been written since the delete. ``_orphaned`` is the same
    value after that write. The operator's decision is about both.
    """
    if key in data and key != ORPHANED_KEY:
        return True
    orphaned = data.get(ORPHANED_KEY)
    return isinstance(orphaned, dict) and key in orphaned


async def _records(db: AsyncSession, rtype: RecordType, batch_size: int):
    last_id = 0
    while True:
        rows = (
            (
                await db.execute(
                    select(Record)
                    .where(Record.type_id == rtype.id, Record.id > last_id)
                    .order_by(Record.id)
                    .limit(batch_size)
                    .execution_options(include_deleted=True)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return
        yield rows
        last_id = rows[-1].id or last_id


async def count_conflicts(
    db: AsyncSession, rtype: RecordType, keys: list[str], *, batch_size: int
) -> dict[str, int]:
    """``{key: how many records still hold a value for it}``, keys with none
    omitted. Empty when ``keys`` is empty, without touching the database."""
    if not keys:
        return {}
    counts: dict[str, int] = {}
    async for batch in _records(db, rtype, batch_size):
        for record in batch:
            data = dict(record.data or {})
            for key in keys:
                if _payload_holds(data, key):
                    counts[key] = counts.get(key, 0) + 1
    return {key: counts[key] for key in keys if key in counts}


async def discard(db: AsyncSession, rtype: RecordType, keys: list[str], *, batch_size: int) -> int:
    """Drop ``keys`` from every record's payload. Returns the rows touched.

    The one deliberate bulk write in the whole of §8, and it is allowed
    precisely because of what it is not: it touches only the reserved sub-key
    and the not-yet-migrated top-level copy of a *removed* field, never a value
    the current schema describes; the operator asked for it by name; and it is
    idempotent, so an interrupted run is finished by running it again.

    ``data`` is reassigned rather than mutated — a plain ``JSON`` column has no
    mutation tracking, so an in-place ``pop()`` is a change SQLAlchemy never
    sees and never writes.

    ``version`` is deliberately not bumped. Optimistic concurrency is about an
    editor holding a stale copy of the *shape*, and no editor has ever seen
    this sub-key: a client cannot read it as a field or write it back
    (``_payload.validate`` refuses a payload carrying it), so there is no
    concurrent edit for a bump to protect and every open editor would be
    invalidated for a change none of them can observe.
    """
    if not keys:
        return 0
    touched = 0
    async for batch in _records(db, rtype, batch_size):
        for record in batch:
            data = dict(record.data or {})
            orphaned = dict(data.get(ORPHANED_KEY) or {})
            changed = False
            for key in keys:
                if key in data and key != ORPHANED_KEY:
                    data.pop(key)
                    changed = True
                if key in orphaned:
                    orphaned.pop(key)
                    changed = True
            if not changed:
                continue
            if orphaned:
                data[ORPHANED_KEY] = orphaned
            else:
                data.pop(ORPHANED_KEY, None)
            record.data = data
            db.add(record)
            touched += 1
        await db.flush()
    if touched:
        mark_written(db)
        # Every record of the type just had keys removed from its payload, and
        # a reduce spec folds on that payload — so a spec grouping on (or
        # valuing) a discarded key is stale from here on. It carries no
        # ``reindex_pending`` marker and never will (a spec is a deployment,
        # not a schema edit), so nothing else would rebuild it. Inert with no
        # spec registered: this issues no statements at all.
        await rebuild_type(db, rtype, batch_size=batch_size)
    return touched
