"""Rebuilding a reduce index from the records, and checking the stored rows.

Phase 5 §5.2's second and third legs. The delta
(:mod:`sm_records.index._reduce_write`) is fast and incremental and therefore
the part that can go wrong; these two are what make that acceptable.

**Why this walks the records in Python rather than issuing one
``INSERT … SELECT … GROUP BY``.** The design sketched the SQL form, and it is
the right shape — but it is only expressible when the group is a column the
database can see. A :class:`~sm_records.index.reduce.ReduceSpec`'s ``group_by``
is an arbitrary Python callable over the whole record (that is the point of
the seam: a bucket, a derived key, a value read out of the payload), so there
is no expression to ``GROUP BY``. The rebuild therefore reads the records in
batches, accumulates ``{group: (count, sum)}`` in memory, and bulk-inserts the
result — one statement per table per rebuild rather than per group. What is
bounded is the number of *records* held at once (the batch) and the number of
*groups* (the accumulator); a spec whose groups are unbounded — one per record
— is a spec whose stored table is as big as the type, which the README warns
about because no implementation here can fix it.

The trash is **excluded**, deliberately and unlike the map-index rebuild.
Index rows survive a soft delete because every query joins back to
``records_record`` and the framework's filter hides the row there (§7.3); a
reduce row has no record to join back to, so a trashed record that stayed
counted would be counted forever. The delta agrees: a trash decrements.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index._drift import clear_drift, record_drift
from sm_records.index._reduce_write import drop_type_rows, stored_rows
from sm_records.index.reduce import ReduceSpec, contribution, reduce_specs
from sm_records.models import IndexReduce, RecordType, tables_for
from sm_records.services._common import utcnow

__all__ = ["Drift", "rebuild_type", "recompute", "verify_type"]


@dataclass(frozen=True, slots=True)
class Drift:
    """One ``(type, key, group)`` whose stored row disagrees with the records.

    ``stored`` is ``None`` for a group the records produce and the table does
    not (a lost increment); ``actual`` is ``None`` for the opposite (a lost
    decrement, or a rebuild that never ran after a spec changed).
    """

    type_key: str
    key: str
    group: str
    stored: tuple[int, Decimal | None] | None
    actual: tuple[int, Decimal | None] | None

    def describe(self) -> str:
        return (
            f"{self.type_key}/{self.key} group {self.group!r}: "
            f"stored {self.stored}, records say {self.actual}"
        )


async def recompute(
    db: AsyncSession, rtype: RecordType, spec: ReduceSpec, *, batch_size: int
) -> dict[str, tuple[int, Decimal | None]]:
    """Fold every **live** record of ``rtype`` through ``spec``.

    Keyset by ``id`` and not ``OFFSET``, for the reason
    :func:`sm_records.index.reindex.reindex_type` gives: the walk may run
    while the type is being written to, and an offset walk over a table being
    written to skips rows.

    The walk reads ``rtype``'s own table set (Phase 5 §6.3); the reduce rows it
    produces go in the **global** reduce table either way, which is keyed by
    ``type_id`` and stays shared (§6.4).
    """
    record_cls = tables_for(rtype).record
    totals: dict[str, tuple[int, Decimal | None]] = {}
    last_id = 0
    while True:
        batch = (
            (
                await db.execute(
                    select(record_cls)
                    .where(record_cls.type_id == rtype.id, record_cls.id > last_id)
                    .order_by(record_cls.id)
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )
        if not batch:
            return totals
        for record in batch:
            last_id = record.id or last_id
            found = contribution(spec, record, rtype)
            if found is None:
                continue
            group, amount = found
            count, total = totals.get(group, (0, None if spec.value is None else Decimal(0)))
            totals[group] = (
                count + 1,
                None if spec.value is None else (total or Decimal(0)) + amount,
            )


async def rebuild_type(
    db: AsyncSession, rtype: RecordType, *, batch_size: int, specs: Sequence[ReduceSpec] = ()
) -> int:
    """Throw away the type's stored groups and recompute them. Returns the row
    count written.

    Idempotent, like every other rebuild in this module: it deletes before it
    writes, so running it twice converges and a crash halfway is recovered by
    running it again. Nothing commits here — the caller owns the transaction,
    which is what lets the reindex runner commit per type.

    With no spec registered this issues **no statements at all**: it does not
    even delete, because a host that has never registered a spec has no rows
    and a blanket ``DELETE`` per type would be a statement every reindex pays
    for a feature it does not use.
    """
    chosen = tuple(specs) or reduce_specs()
    if not chosen:
        return 0
    # Before the work, not after: the rows this run writes are correct by
    # construction, so whatever a previous verify found about this type is
    # answered the moment the rebuild starts writing them.
    clear_drift(rtype.id)
    now = utcnow()
    written = 0
    for spec in chosen:
        await drop_type_rows(db, rtype.id, spec.key)
        totals = await recompute(db, rtype, spec, batch_size=batch_size)
        if not totals:
            continue
        await db.execute(
            insert(IndexReduce),
            [
                {
                    "type_id": rtype.id,
                    "key": spec.key,
                    "group_value": group,
                    "count": count,
                    "sum": total,
                    "updated_at": now,
                }
                for group, (count, total) in totals.items()
            ],
        )
        written += len(totals)
    return written


def _same(left: Decimal | None, right: Decimal | None) -> bool:
    """Decimal equality that tolerates the scale the column rounds to.

    ``Numeric(19, 5)`` is exact on Postgres and stored as ``REAL`` on SQLite
    (:mod:`sm_records.models._index` says so), so a sum read back may differ
    from the one just folded in the last place. Comparing the quantised values
    is what keeps the verifier from reporting the dev backend's float as drift.
    """
    if left is None or right is None:
        return left is right or left == right
    return left.quantize(Decimal("0.00001")) == right.quantize(Decimal("0.00001"))


async def verify_type(
    db: AsyncSession, rtype: RecordType, *, batch_size: int, specs: Sequence[ReduceSpec] = ()
) -> list[Drift]:
    """Recompute every spec from the records and report what disagrees.

    Read-only: it never writes the correction it finds. That is deliberate —
    an aggregate silently repaired is an aggregate whose drift nobody ever
    learns about, and knowing *that* it drifted is the whole value of the
    check (§7.5). The repair is ``reindex``, which is one command away and
    says what it did.
    """
    chosen = tuple(specs) or reduce_specs()
    drifts: list[Drift] = []
    for spec in chosen:
        actual = await recompute(db, rtype, spec, batch_size=batch_size)
        stored = {
            row.group_value: (int(row.count), row.sum)
            for row in await stored_rows(db, rtype.id, spec.key)
        }
        for group in sorted(set(stored) | set(actual)):
            left, right = stored.get(group), actual.get(group)
            matches = (
                left is not None
                and right is not None
                and left[0] == right[0]
                and _same(left[1], right[1])
            )
            if matches:
                continue
            drifts.append(Drift(rtype.key, spec.key, group, left, right))
    # Positive evidence either way: a clean verify clears what an earlier one
    # recorded, which is what makes the health detail say "it drifted" rather
    # than "it drifted at some point and may or may not still".
    record_drift(rtype.id, drifts)
    return drifts
