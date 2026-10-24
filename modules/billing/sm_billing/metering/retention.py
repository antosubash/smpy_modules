"""The ledger retention purge, in short bounded batches.

- **A charge and its refund go together.** Rows are selected by the age of
  the *charge* (every kind except ``refund``), and one ``DELETE`` removes
  those rows and their ``<key>:refund`` partners. A refund is always younger
  than its charge, so purging by each row's own age would delete the charge
  and keep the refund; the key would then replay as ``Refunded`` and a
  genuine refund of a new call under it would conflict. (``adjust:`` rows
  have no partner: each is its own key.)
- **Bounded.** ``PURGE_BATCH`` rows per transaction, each finished with
  ``finalize_session``, and at most ``MAX_BATCHES`` per call. A backlog
  (after an outage, or after the retention was lowered) is worked off over
  several ticks instead of holding SQLite's one write lock long enough to
  turn reserves into ``usage_busy`` and stall expiry.
- **Read, then write.** The ids are selected in a session of their own and
  the ``DELETE`` is the write session's first statement: a write transaction
  that read first can fail on SQLite with ``SQLITE_BUSY_SNAPSHOT``. Two
  instances purging at once delete the same rows; the second matches none.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from simple_module_db import finalize_session, mark_written
from sqlalchemy import delete, or_, select, tuple_

from sm_billing.contracts.metering import HoldStatus
from sm_billing.metering.validate import REFUND, REFUND_SUFFIX
from sm_billing.models import UsageEvent, UsageHold

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from sm_billing.metering.service import UsageService

#: Rows selected per transaction (each charge may take its refund with it).
PURGE_BATCH = 1000
#: Transactions per table per call; the rest waits for the next tick.
MAX_BATCHES = 20
#: Released and expired holds are kept this long, for the admin screens.
SETTLED_HOLD_DAYS = 30
_SETTLED = (HoldStatus.RELEASED.value, HoldStatus.EXPIRED.value)


@dataclass
class Purged:
    events: int = 0
    holds: int = 0
    #: ``False`` when the batch budget ran out with rows left to purge.
    done: bool = True


async def _delete(factory: async_sessionmaker, stmt) -> int:
    async with factory() as session:
        result = await session.execute(stmt)
        mark_written(session)
        await finalize_session(session)
    return int(result.rowcount or 0)  # ty: ignore[unresolved-attribute] - CursorResult


async def _event_batch(factory: async_sessionmaker, cutoff: datetime, size: int) -> tuple[int, int]:
    """One batch of old charges and their refunds: ``(selected, deleted)``."""
    stmt = (
        select(UsageEvent.id, UsageEvent.tenant_id, UsageEvent.meter, UsageEvent.idempotency_key)
        .where(UsageEvent.kind != REFUND, UsageEvent.recorded_at < cutoff)
        .order_by(UsageEvent.id)
        .limit(size)
    )
    async with factory() as session:
        rows = (await session.execute(stmt)).all()
    if not rows:
        return 0, 0
    partners = [(r.tenant_id, r.meter, r.idempotency_key + REFUND_SUFFIX) for r in rows]
    key = tuple_(UsageEvent.tenant_id, UsageEvent.meter, UsageEvent.idempotency_key)
    deleted = await _delete(
        factory,
        delete(UsageEvent).where(
            or_(
                UsageEvent.id.in_([r.id for r in rows]),
                (UsageEvent.kind == REFUND) & key.in_(partners),
            )
        ),
    )
    return len(rows), deleted


async def _hold_batch(factory: async_sessionmaker, cutoff: datetime, size: int) -> tuple[int, int]:
    stmt = (
        select(UsageHold.id)
        .where(UsageHold.status.in_(_SETTLED), UsageHold.settled_at < cutoff)
        .order_by(UsageHold.settled_at)
        .limit(size)
    )
    async with factory() as session:
        ids = list((await session.scalars(stmt)).all())
    if not ids:
        return 0, 0
    deleted = await _delete(
        factory, delete(UsageHold).where(UsageHold.id.in_(ids), UsageHold.status.in_(_SETTLED))
    )
    return len(ids), deleted


async def purge(
    usage: UsageService,
    retention_days: int,
    *,
    batch: int | None = None,
    max_batches: int | None = None,
) -> Purged:
    """Delete ledger rows past ``retention_days`` (``0``: keep them) and holds
    settled more than ``SETTLED_HOLD_DAYS`` ago, at most ``max_batches``
    transactions of ``batch`` rows for each of the two tables."""
    size = batch or PURGE_BATCH
    budget = max_batches or MAX_BATCHES
    now, factory, out = usage.now(), usage.session_factory, Purged()
    work = [(_hold_batch, now - timedelta(days=SETTLED_HOLD_DAYS), "holds")]
    if retention_days > 0:
        work.insert(0, (_event_batch, now - timedelta(days=retention_days), "events"))
    for run, cutoff, field in work:
        for _ in range(budget):
            selected, deleted = await run(factory, cutoff, size)
            setattr(out, field, getattr(out, field) + deleted)
            if selected < size:
                break
        else:
            out.done = False  # the budget ran out with rows (maybe) left
    return out
