"""Rebuilding index rows from the documents that are their source of truth.

Index rows are derived, so a bug in the maintenance path produces wrong query
results rather than slow ones — that is the honest cost of the whole index
layer, and this module is the mitigation both YesSql and Orchard ship (design
doc §7.7). It is idempotent by construction: every record's rows are deleted
and rewritten from ``data``, so a crash anywhere is recovered by running it
again.

It is also the eager half of design doc §8.3. Payloads migrate lazily, one
edit at a time; indexes are rewritten in full on every schema change, because
a stale index is a wrong answer rather than a cosmetic lag. A ``text`` field
that became a ``number`` gets ``123`` into ``records_index_number`` while the
payload keeps ``"123"`` forever, and ``price > 100`` is correct the moment
this finishes — with no row having been rewritten.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.providers import TypeResolver
from sm_records.index.writer import write_index
from sm_records.models import Record, RecordType


async def reindex_record(
    db: AsyncSession,
    record: Record,
    rtype: RecordType,
    *,
    resolve_type_id: TypeResolver,
) -> None:
    """One record. Thin by design — the writer already rebuilds the whole set,
    so "reindex" and "write" are the same operation seen from two places."""
    await write_index(db, record, rtype, resolve_type_id=resolve_type_id)


async def reindex_type(
    db: AsyncSession,
    rtype: RecordType,
    *,
    resolve_type_id: TypeResolver,
    batch_size: int,
    field_keys: Sequence[str] | None = None,
) -> int:
    """Rebuild the index for every record of ``rtype``. Returns the count.

    ``field_keys`` names the fields a schema change touched. It is accepted
    and deliberately not used to narrow the work: a record's rows are rewritten
    whole. Deleting and reprojecting only the named keys is a real optimisation
    — it would leave the other fields' rows untouched on a big type — but it is
    also the version that can leave one field's rows stale if the caller's list
    is wrong, and the simplest correct thing has to exist first.

    Soft-deleted records are included (``include_deleted``). Their index rows
    stay in place while they are in the trash — every query joins back to
    ``records_record``, where the framework's filter hides them (§7.3) — so
    skipping them here would quietly empty the index of a record that a restore
    is supposed to bring back whole.

    Batching bounds the number of rows in memory, not the transaction: nothing
    here commits, and a long-running rebuild that wants to commit per batch
    does it in the caller, which is the only place that knows whether a partial
    rebuild is acceptable. It is, in fact — the operation is idempotent.
    """
    total = 0
    last_id = 0
    while True:
        batch = (
            (
                await db.execute(
                    select(Record)
                    .where(Record.type_id == rtype.id, Record.id > last_id)
                    .order_by(Record.id)
                    .limit(batch_size)
                    # Keyset, not OFFSET: the rebuild writes as it reads, and an
                    # offset walk over a table being written to skips rows.
                    .execution_options(include_deleted=True)
                )
            )
            .scalars()
            .all()
        )
        if not batch:
            return total
        for record in batch:
            await reindex_record(db, record, rtype, resolve_type_id=resolve_type_id)
            last_id = record.id or last_id
            total += 1


async def clear_pending(db: AsyncSession, rtype: RecordType, field_keys: Sequence[str]) -> None:
    """Drop ``field_keys`` from ``reindex_pending`` — step 4 of design doc §8.5.

    Separate from the rebuild because the service owns the sequence around it
    (bump ``schema_version``, mark pending, reindex into the new table, delete
    the old rows, then this). Assigning a new list rather than mutating the old
    one is not style: the column is plain ``JSON`` with no mutation tracking,
    so an in-place ``remove()`` is a change SQLAlchemy never sees and never
    writes — and the field stays refused as a filter forever.
    """
    dropped = set(field_keys)
    rtype.reindex_pending = [key for key in (rtype.reindex_pending or []) if key not in dropped]
    db.add(rtype)
    await db.flush()
