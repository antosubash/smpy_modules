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

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index._batch import current_batch
from sm_records.index.providers import TypeResolver
from sm_records.index.reduce_rebuild import rebuild_type
from sm_records.index.writer import project, row_values, write_index
from sm_records.models import RecordType, tables_for
from sm_records.services._common import walk_type


async def reindex_record(
    db: AsyncSession,
    record,
    rtype: RecordType,
    *,
    resolve_type_id: TypeResolver,
) -> None:
    """One record. Thin by design — the writer already rebuilds the whole set,
    so "reindex" and "write" are the same operation seen from two places."""
    await write_index(db, record, rtype, resolve_type_id=resolve_type_id)


async def reindex_batch(
    db: AsyncSession,
    records: Sequence[Any],
    rtype: RecordType,
    *,
    resolve_type_id: TypeResolver,
    touched: set[str] | None = None,
) -> None:
    """Rebuild the index rows of a whole batch: **one statement per table**.

    Same delete-then-insert as :func:`~sm_records.index.writer.write_index`
    and the same projection (:func:`~sm_records.index.writer.project` and
    :func:`~sm_records.index.writer.row_values`), so a rebuilt row is
    byte-for-byte what an ordinary write would have produced — pinned by
    ``tests/test_index_reindex.py``, which compares the two snapshots
    id-free. What changes is only how many round trips it takes: six
    ``DELETE``s, a handful of ORM inserts and a flush *per record* became six
    ``DELETE … WHERE record_id IN (:batch)`` and at most six executemany
    ``INSERT``s *per batch*. That is where the rebuild's ~130 rec/s went.

    The delete pass covers **all six tables** and not only the ones this batch
    has rows for: a field that changed kind, or stopped being indexed, has
    rows in a table the new projection yields nothing for, and those are
    exactly the rows a rebuild exists to remove.

    It is keyed on ``record_id`` alone, as ``delete_index`` is — a record's
    rows all belong to it, and scoping by ``type_id`` as well would only
    hide rows written under a type id the record no longer has.

    ``touched`` collects the table names actually written, for a caller that
    wants to ``ANALYZE`` them afterwards.

    **Core DML does not fire the framework's ``after_flush`` listener**, so a
    caller inside a request must mark the session written itself. Every caller
    today is :func:`reindex_type` under
    :mod:`sm_records.services.reindex_runner`, which owns its own session and
    commits explicitly.

    **The batch is re-read here, not projected as the caller read it.** The
    runner commits per batch, so the caller's ``SELECT`` and this function's
    ``DELETE`` are in the same transaction but not in the same instant, and an
    ordinary edit committed in between would have its index rows deleted and
    replaced by a projection of the pre-edit payload — permanently.
    :func:`sm_records.index._batch.current_batch` re-reads the rows under a
    row lock where the dialect has one and drops the ones whose ``version``
    moved; a dropped row keeps the rows its own writer wrote, which are
    already right, and is not touched at all. That is why the ``DELETE`` is
    keyed on the ids of the *kept* rows rather than on the caller's batch.
    """
    kept = await current_batch(db, records, rtype)
    ids = [record.id for record in kept if record.id is not None]
    if not ids:
        return
    tables = tables_for(rtype)
    rows: dict[type, list[dict]] = {}
    for record in kept:
        for entry in project(record, rtype, resolve_type_id):
            table, values = row_values(tables, entry, record.id, rtype.id)
            rows.setdefault(table, []).append(values)

    for table in tables.index_tables:
        await db.execute(delete(table).where(table.record_id.in_(ids)))
    for table, values_list in rows.items():
        await db.execute(insert(table), values_list)
        if touched is not None:
            touched.add(str(table.__tablename__))


async def reindex_type(
    db: AsyncSession,
    rtype: RecordType,
    *,
    resolve_type_id: TypeResolver,
    batch_size: int,
    field_keys: Sequence[str] | None = None,
    after_batch: Callable[[], Awaitable[None]] | None = None,
    touched: set[str] | None = None,
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

    A batch is also the unit of *writing* (:func:`reindex_batch`), not only of
    reading: one ``DELETE`` and one bulk ``INSERT`` per index table per batch.
    ``touched`` is passed through to it and names the tables written, for a
    caller that wants to ``ANALYZE`` them once the walk is done.

    The count is of records *walked*, not of records whose rows this run
    rewrote: :func:`reindex_batch` drops a record another writer has committed
    since the batch was read, because that writer already wrote its index rows
    from the payload it stored. Counting it as walked is the honest number —
    the walk did reach it and the type's index is complete when the walk ends.

    Batching bounds the number of rows in memory, not the transaction: nothing
    here commits, and a long-running rebuild that wants to commit per batch
    does it in the caller, which is the only place that knows whether a partial
    rebuild is acceptable. It is, in fact — the operation is idempotent. That
    caller passes ``after_batch``, which is called with the batch written and
    before the next one is read: :func:`sm_records.services.reindex_runner.run_pending`
    passes ``session.commit``, so a rebuild of a large type holds SQLite's
    single write lock for one batch at a time rather than for the whole walk.
    """
    total = 0
    # Keyset, not OFFSET: the rebuild writes as it reads (``walk_type``).
    async for batch in walk_type(db, rtype, batch_size):
        await reindex_batch(db, batch, rtype, resolve_type_id=resolve_type_id, touched=touched)
        total += len(batch)
        if after_batch is not None:
            await after_batch()
    # After the map rows, never interleaved with them: a reduce row is a fold
    # over *many* records, so it cannot be rebuilt batch by batch alongside
    # the projection of one. It is deleted and recomputed in its own pass per
    # spec, which is also why it is safe to run here — the walk above has
    # finished and nothing in this transaction is half-written. With no spec
    # registered this issues no statements at all (Phase 5 §5.2).
    await rebuild_type(db, rtype, batch_size=batch_size)
    return total


def pending_map(rtype: RecordType) -> dict[str, str]:
    """``reindex_pending`` as a mapping, whatever is actually in the column.

    It was a plain list of keys before Phase 3 and is a ``{key: enqueued-at}``
    mapping now, on the same ``JSON`` column with no migration between them —
    so a row written by the older code can still be sitting there mid-rebuild
    at upgrade time. Reading it as a list and crashing would turn that into a
    500 on the health check; reading it as "pending, start unknown" finishes
    the rebuild, which is what the row is asking for.
    """
    raw = rtype.reindex_pending or {}
    if isinstance(raw, list):
        return {str(key): "" for key in raw}
    return dict(raw)


async def load_fresh(db: AsyncSession, rtype: RecordType) -> RecordType:
    """Re-read the type row *inside the caller's transaction*, overwriting what
    the identity map holds (``populate_existing``).

    The caller has usually been holding ``rtype`` for the length of a rebuild,
    which is exactly as long as it takes another session to commit a second
    schema change to the same row. Everything this module writes back to the
    type row therefore starts from the row as it is now, not as it was read.
    Falls back to the instance passed in when the row has gone, so a type
    deleted mid-rebuild is not an ``AttributeError``.
    """
    fresh = (
        (
            await db.execute(
                select(RecordType)
                .where(RecordType.id == rtype.id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .first()
    )
    return fresh if fresh is not None else rtype


async def clear_pending(db: AsyncSession, rtype: RecordType, field_keys: Sequence[str]) -> None:
    """Drop ``field_keys`` from ``reindex_pending`` — step 4 of design doc §8.5.

    Separate from the rebuild because the service owns the sequence around it
    (bump ``schema_version``, mark pending, reindex into the new table, delete
    the old rows, then this). Assigning a new mapping rather than mutating the
    stored one is not style: the column is plain ``JSON`` with no mutation
    tracking, so an in-place ``pop()`` is a change SQLAlchemy never sees and
    never writes — and the field stays refused as a filter forever.

    **The keys are removed one at a time from a freshly loaded row**, never by
    assigning back a mapping read before the rebuild started. ``reindex_pending``
    maps each key to the instant it was enqueued
    (:class:`~sm_records.models.RecordType`), and a run that assigned its own
    snapshot back would erase every marker a *later* schema change added —
    silently leaving a field that nothing ever rebuilds. Clearing per key
    against the current row leaves those markers for the next run, which is the
    behaviour a concurrent second edit needs.
    """
    fresh = await load_fresh(db, rtype)
    pending = pending_map(fresh)
    for key in field_keys:
        pending.pop(key, None)
    fresh.reindex_pending = pending
    db.add(fresh)
    await db.flush()


async def delete_field_rows(db: AsyncSession, rtype: RecordType, field_keys: Sequence[str]) -> int:
    """Delete every index row of ``rtype`` for the named keys, across all six
    tables. Returns the number of rows removed.

    Step 3 of design doc §8.5, and the one step :func:`reindex_type` does not
    already cover *by name*: it rewrites each record's rows whole, so a removed
    field's rows do disappear with it — but only for records the rebuild
    reaches. Doing it as one statement per table first means a field deleted
    from a type with no records left, or a rebuild that dies halfway, still
    leaves nothing behind that a query could read as truth.
    """
    removed = 0
    for table in tables_for(rtype).index_tables:
        result = await db.execute(
            delete(table).where(table.type_id == rtype.id, table.field_key.in_(list(field_keys)))
        )
        removed += result.rowcount or 0
    return removed
