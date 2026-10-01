"""Re-reading a batch of records inside the transaction that rewrites them.

Every batched maintenance walk in this module has the same shape: read a page
of records, derive something from their payloads, write it back. The read and
the write are two statements, and between them another request can commit an
ordinary edit — which is not a lag but a permanent wrong answer, because the
walk then writes rows derived from the payload it read *over* the rows the
editor derived from the payload it wrote. The index says ``name = 'old'``
about a record whose ``data`` says ``'new'``, until somebody reindexes again:
exactly the "wrong query results, not slow ones" that design doc §7.7 is
written to prevent.

:func:`current_batch` closes the window with the two things the database
actually offers:

* **A lock, where there is one.** On Postgres the re-read is
  ``SELECT … FOR UPDATE``, so a writer that has not started yet blocks at its
  own ``UPDATE`` of the record row until the walk commits — and its index
  write, which follows that ``UPDATE``, lands after ours rather than under it.
* **A version comparison, always.** A writer that committed *before* the
  re-read has already bumped ``Record.version`` and has already written the
  correct index rows for its own payload. Such a row is dropped from the
  batch: not rewritten, not deleted, left exactly as its writer left it. The
  walk is idempotent and restartable (§7.7), so "skip it this run" is a
  complete answer.

SQLite has no row locks — ``FOR UPDATE`` compiles there to a plain ``SELECT``,
the trap :func:`sm_records.services._claims.lock_type` documents at length —
so it gets the version comparison alone. The residual window between the
re-read and the first write of the batch is the one SQLite closes itself: a
write issued from a transaction whose read snapshot has since been superseded
comes back ``database is locked``, which
:func:`sm_records.services.reindex_runner.run_pending` already retries from the
top on a fresh session.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import RecordType, tables_for

__all__ = ["current_batch"]


async def current_batch(db: AsyncSession, records: Sequence[Any], rtype: RecordType) -> list[Any]:
    """The rows of ``records`` that are still as the caller read them.

    Re-reads them in ``db``'s current transaction — locking on Postgres — and
    returns the subset whose ``version`` has not moved, refreshed from the row
    (``populate_existing``) so a caller that projects from the instance is
    projecting from what the database holds now.

    ``include_deleted``: the walks that call this include the trash, and a
    record soft-deleted between the two reads must still be found, or the
    version comparison would silently drop it as "gone" rather than as
    "already handled".

    Called with an empty sequence, or one whose rows have all gone, it returns
    an empty list and issues no statement.
    """
    seen = {record.id: record.version for record in records if record.id is not None}
    if not seen:
        return []
    record_cls = tables_for(rtype).record
    stmt = (
        select(record_cls)
        .where(record_cls.id.in_(list(seen)))
        .order_by(record_cls.id)
        .execution_options(include_deleted=True, populate_existing=True)
    )
    if db.get_bind().dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    rows = (await db.execute(stmt)).scalars().all()
    return [row for row in rows if row.version == seen.get(row.id)]
