"""Rebuilding the denormalised ``display_title`` of every record of a type.

Split out of :mod:`sm_records.services.reindex_runner` for the 300-line cap.
The seam is the one the runner already draws in its own docstring: that module
sequences a pending rebuild (which markers, which order, when to clear them),
this one is a single batched walk it calls.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index._batch import current_batch
from sm_records.models import RecordType
from sm_records.schema.compile import from_stored
from sm_records.services._common import walk_type
from sm_records.services._payload import display_title, field_defs

__all__ = ["recompute_titles"]


async def recompute_titles(db: AsyncSession, rtype: RecordType, batch_size: int) -> int:
    """Rebuild every record's denormalised ``display_title`` (§18 Q2).

    Resolved there in favour of the reindex owning it, because that is where
    the batched, resumable machinery already is. Read through ``from_stored``
    so the title comes from the value as the *current* schema reads it — a
    ``number`` that is still stored as the string a ``text`` field wrote.

    The trash is included: a restored record showing the title of a pointer
    that was replaced months ago is exactly the staleness this fixes.

    Each batch is re-read through :func:`sm_records.index._batch.current_batch`
    before anything is assigned, for the reason that function exists: the walk
    commits per batch, and a record edited between the keyset read and the
    commit would have the title derived from its *old* payload written over
    the one its own writer derived from the new one. A record whose version
    moved is left alone — its writer computed the title from the payload it
    stored, so it is already right — and the keyset still advances past it, so
    the walk cannot loop.

    Returns the number of records walked, which includes those skipped: the
    walk reached them and their titles are correct when it ends.
    """
    defs = field_defs(rtype)
    total = 0
    async for batch in walk_type(db, rtype, batch_size):
        total += len(batch)
        for record in await current_batch(db, batch, rtype):
            values = from_stored(defs, dict(record.data or {}))
            record.display_title = display_title(rtype, values)
            db.add(record)
        # Committed rather than flushed, for the reason ``run_pending`` gives
        # ``reindex_type``'s ``after_batch``: one batch of the write lock at a
        # time, and a half-finished title pass is repeated by the next run.
        await db.commit()
    return total
