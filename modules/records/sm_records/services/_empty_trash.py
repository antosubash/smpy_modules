"""Emptying a type's trash, set-based — and the identity a purge leaves behind.

Split out of :mod:`sm_records.services.bulk` for the file cap, along the seam
that module's docstring already draws: everything there is a pass over records
one at a time through the single-record service, and everything here is one
statement per table over a set of them. ``bulk`` re-exports both names, so
callers still import one module.

The shape is :func:`~sm_records.services._lifecycle.purge_type_records`'s,
narrowed from "every record of the type" to "every trashed record matching
this filter", and it keeps that function's two rules: read the identity
columns *before* deleting, because a ``RecordPurged`` is the one event nobody
can reconstruct afterwards, and mark the session written by hand, because core
DML does not fire ``after_flush``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.query import Filter, filtered, only_trashed
from sm_records.models import RecordType, tables_for
from sm_records.services._common import mark_written

__all__ = ["Identity", "empty_trash"]

_CHUNK = 500
"""How many ids one ``IN`` clause of the purge carries. A trash holding a
hundred thousand rows is one bind parameter per row otherwise, which asyncpg
refuses outright past 32,767 — and a statement that size is not one any
planner handles gracefully either."""


@dataclass(slots=True)
class Identity:
    """The three columns a ``RecordPurged`` carries, kept after the row is gone.

    The shape ``services._common.PurgedRecord`` names for the type delete,
    spelled as a dataclass because these are read as a column select and
    handed straight to the event builder.
    """

    uuid: str
    locale: str
    translation_group: str


async def _purge_ids(db: AsyncSession, rtype: RecordType, ids: list[int]) -> None:
    """Really delete these rows, and their index and revision rows.

    By id and in chunks rather than by the filter that selected them: the
    filter compiles to a semi-join over the index tables, and this deletes
    those first, so a second evaluation would match nothing. Index rows go
    first for the same reason ``purge_type_records`` deletes revisions before
    documents — every statement here reads what a later one removes.

    **No reduce delta.** A trashed record was decremented out of every
    maintained aggregate when it was trashed (``_lifecycle._trash``), and only
    trashed records reach here, so a second decrement would take the group
    below the truth.
    """
    tables = tables_for(rtype)
    for start in range(0, len(ids), _CHUNK):
        batch = ids[start : start + _CHUNK]
        for table in tables.index_tables:
            await db.execute(sa_delete(table).where(table.record_id.in_(batch)))
        await db.execute(sa_delete(tables.revision).where(tables.revision.record_id.in_(batch)))
        await db.execute(sa_delete(tables.record).where(tables.record.id.in_(batch)))
    await db.flush()
    mark_written(db)


async def empty_trash(
    db: AsyncSession,
    rtype: RecordType,
    *,
    filters: Sequence[Filter] = (),
) -> list[Identity]:
    """Purge every trashed record of ``rtype``, or the filtered part of it.

    Returns the identity of each record purged — the endpoint publishes one
    ``RecordPurged`` per entry, which is the contract every other purge keeps
    and the only way a subscriber hears about a record that is no longer there
    to be read.

    ``filters`` is the listing grammar's, unchanged and refused the same way
    (``QueryError`` propagates; the endpoint layer owns the 400/409 split), so
    "empty the part of the trash this screen is showing" is the query the
    screen listed it with. Index rows survive a soft delete (§7.3), which is
    what makes the trash filterable at all.
    """
    cls = tables_for(rtype).record
    # Four columns and no entity: the identities the events need and the ids
    # the delete needs, in one statement rather than ten thousand ORM
    # instantiations. Naming the mapper's columns is what keeps the
    # soft-delete filter attached, which ``only_trashed`` then lifts and
    # replaces with "the trash and only the trash".
    columns = select(cls.id, cls.uuid, cls.locale, cls.translation_group).where(
        cls.type_id == rtype.id
    )
    stmt = only_trashed(cls, filtered(columns, rtype, list(rtype.fields or []), filters))
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []
    await _purge_ids(db, rtype, [row[0] for row in rows])
    return [Identity(row[1], row[2], row[3]) for row in rows]
