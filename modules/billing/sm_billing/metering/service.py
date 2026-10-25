"""``UsageService`` — billing's ``UsageMeter``, installed as ``app.state.billing_usage``.

Every call reads first and writes second, in **separate** transactions:

1. The plan's limit and the current period are read in a short session of
   their own (``effective_plan``), closed before any write starts.
2. The write session's first statement is the ledger ``INSERT``. On SQLite
   that takes the write lock at once, so a concurrent writer waits on
   ``busy_timeout`` and then runs against fresh committed state; a
   transaction that had *read* first would instead hold a stale snapshot and
   fail with ``SQLITE_BUSY_SNAPSHOT``, which ``busy_timeout`` cannot wait out.
3. The counter moves only through ``sql.upsert_period``'s conditional
   upsert, so the check and the increment are one statement.

How the write is wrapped (own transaction or the caller's savepoint) is
``metering.tx``; the shared read side is ``metering.core``, and the gauge
holds are ``metering.holds``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import update

from sm_billing.contracts.metering import (
    Allowed,
    Exceeded,
    IdempotencyConflict,
    MeterKind,
    Refunded,
)
from sm_billing.metering import sql
from sm_billing.metering.core import Resolved as _Resolved
from sm_billing.metering.holds import HoldsMixin
from sm_billing.metering.periods import as_utc
from sm_billing.metering.tx import Apply, Counted, find_event, period_row, run_write
from sm_billing.metering.validate import (
    ADJUST,
    ADJUST_PREFIX,
    ADMIN_SOURCE,
    CONSUME,
    RECORD,
    REFUND,
    REFUND_SUFFIX,
    check_adjust,
    check_call,
)
from sm_billing.models import UsagePeriod

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_REPLAY = "replay"
Outcome = Allowed | Exceeded | Refunded
_COUNTER = MeterKind.COUNTER


class UsageService(HoldsMixin):
    """Per-period counters (here) and gauge holds (``HoldsMixin``)."""

    # ── reads ────────────────────────────────────────────────────────
    async def _used(self, tenant_id: str, meter: str, start: datetime, db=None) -> int:
        async with self._reader(db) as session:
            row = await period_row(session, tenant_id, meter, start)
        return 0 if row is None else int(row.used)

    async def _replay(self, call: dict, res: _Resolved, db=None) -> Allowed | Refunded | None:
        """The original outcome of ``call``'s key, read back from the ledger.

        A key answers only for the call it was first used with: a different
        quantity, kind or source raises ``IdempotencyConflict`` rather than
        replaying an admission it never paid for. A key since refunded
        replays as ``Refunded`` (not admitted); a retry needs a new key.
        """
        tenant_id, meter, key = call["tenant_id"], call["meter"], call["idempotency_key"]
        async with self._reader(db) as session:
            event = await find_event(session, tenant_id, meter, key)
            if event is None:
                return None
            original = (event.kind, int(event.quantity), event.source)
            if original != (call["kind"], call["quantity"], call["source"]):
                raise IdempotencyConflict(key)
            if event.period_start is None:
                return None
            refunded = await find_event(session, tenant_id, meter, key + REFUND_SUFFIX)
            row = await period_row(session, tenant_id, meter, as_utc(event.period_start))
        used, end = (int(row.used), as_utc(row.period_end)) if row else (event.quantity, None)
        if refunded is not None:
            return Refunded(used, res.limit, end)
        return Allowed(used, res.limit, end, replayed=True)

    async def _refuse(self, tenant_id, meter, qty, res: _Resolved, db=None) -> Exceeded:
        used = await self._used(tenant_id, meter, res.period[0], db)
        logger.info(
            "billing: usage refused tenant=%s meter=%s used=%s qty=%s limit=%s",
            tenant_id,
            meter,
            used,
            qty,
            res.limit,
        )
        return Exceeded(used, res.limit or 0, qty, res.period[1])

    async def check(self, tenant_id: str, meter: str, qty: int = 1) -> Allowed | Exceeded:
        self._require(meter, _COUNTER)
        async with self._factory() as session:  # one connection for both reads
            res = await self._resolve(tenant_id, meter, session)
            used = await self._used(tenant_id, meter, res.period[0], session)
        if res.limit is not None and used + qty > res.limit:
            return Exceeded(used, res.limit, qty, res.period[1])
        return Allowed(used, res.limit, res.period[1])

    # ── writes ───────────────────────────────────────────────────────
    def _ledger(self, tenant_id, meter, qty, kind, key, start, *, source, **extra) -> dict:
        now = self._clock()
        return {
            "tenant_id": tenant_id,
            "meter": meter,
            "quantity": qty,
            "kind": kind,
            "idempotency_key": key,
            "period_start": start,
            "occurred_at": as_utc(extra.pop("occurred_at", None) or now),
            "recorded_at": now,
            "source": source,
            **extra,
        }

    @staticmethod
    def _counter(event: dict, res: _Resolved, limit: int | None) -> Apply:
        """Claim the key, then move the counter (within ``limit``)."""
        period = res.period

        async def apply(session: AsyncSession) -> Counted | str | None:
            dialect = session.get_bind().dialect.name
            claimed = await session.execute(sql.insert_event(dialect, **event))
            if claimed.scalar_one_or_none() is None:
                return _REPLAY
            fields = {"tenant_id": event["tenant_id"], "meter": event["meter"]}
            fields["provider"] = res.provider
            qty, now = event["quantity"], event["recorded_at"]
            if limit is not None and qty > limit:
                # Only a credited (negative) counter can fit it; never insert.
                stmt = sql.add_within_limit(
                    **fields, start=period[0], end=period[1], qty=qty, limit=limit, now=now
                )
            else:
                stmt = sql.upsert_period(
                    dialect, **fields, period=period, qty=qty, limit=limit, now=now
                )
            moved = await session.execute(stmt)
            used = moved.scalar_one_or_none()
            return None if used is None else Counted(int(used))

        return apply

    async def _count(self, event: dict, res: _Resolved, limit, db) -> Outcome:
        tenant_id, meter = event["tenant_id"], event["meter"]
        outcome = await run_write(self._factory, db, self._counter(event, res, limit))
        if isinstance(outcome, Counted):
            return Allowed(outcome.used, res.limit, res.period[1])
        if outcome == _REPLAY:
            replayed = await self._replay(event, res, db)
            if replayed is not None:
                return replayed
        return await self._refuse(tenant_id, meter, event["quantity"], res, db)

    async def consume(
        self,
        tenant_id: str,
        meter: str,
        qty: int,
        idempotency_key: str,
        *,
        source: str,
        db: AsyncSession | None = None,
    ) -> Outcome:
        check_call(tenant_id, meter, qty, idempotency_key, source)
        self._require(meter, _COUNTER)
        res = await self._resolve(tenant_id, meter, db)
        event = self._ledger(
            tenant_id, meter, qty, CONSUME, idempotency_key, res.period[0], source=source
        )
        return await self._count(event, res, res.limit, db)

    async def record(
        self,
        tenant_id: str,
        meter: str,
        qty: int,
        idempotency_key: str,
        *,
        source: str,
        occurred_at: datetime | None = None,
        db: AsyncSession | None = None,
    ) -> Allowed | Refunded:
        check_call(tenant_id, meter, qty, idempotency_key, source)
        self._require(meter, _COUNTER)
        res = await self._resolve(tenant_id, meter, db)
        event = self._ledger(
            tenant_id,
            meter,
            qty,
            RECORD,
            idempotency_key,
            res.period[0],
            source=source,
            occurred_at=occurred_at,
        )
        outcome = await self._count(event, res, None, db)
        assert not isinstance(outcome, Exceeded)  # unconditional: never refused
        return outcome

    async def refund(self, tenant_id: str, meter: str, idempotency_key: str) -> bool:
        self._require(meter, _COUNTER)
        async with self._factory() as session:
            original = await find_event(session, tenant_id, meter, idempotency_key)
        if original is None or original.kind not in (CONSUME, RECORD):
            return False
        start, qty = as_utc(original.period_start), int(original.quantity)
        event = self._ledger(
            tenant_id,
            meter,
            -qty,
            REFUND,
            idempotency_key + REFUND_SUFFIX,
            start,
            source=original.source,
        )

        async def apply(session: AsyncSession) -> Counted | None:
            dialect = session.get_bind().dialect.name
            claimed = await session.execute(sql.insert_event(dialect, **event))
            if claimed.scalar_one_or_none() is None:
                return None  # refunded already
            table = UsagePeriod.__table__
            await session.execute(
                update(table)
                .where(
                    table.c.tenant_id == tenant_id,
                    table.c.meter == meter,
                    table.c.period_start == start,
                )
                .values(used=table.c.used - qty, updated_at=event["recorded_at"])
            )
            return Counted(0)

        return isinstance(await run_write(self._factory, None, apply), Counted)

    async def adjust(
        self, tenant_id: str, meter: str, quantity: int, *, reason: str, actor: str | None = None
    ) -> int:
        """An operator's signed correction to the current period; returns ``used``.

        Ledgered as an ``adjust`` row with its reason. A negative quantity is a
        credit and may take ``used`` below zero.
        """
        check_adjust(tenant_id, meter, quantity, reason, actor)
        self._require(meter, _COUNTER)
        res = await self._resolve(tenant_id, meter, None)
        event = self._ledger(
            tenant_id,
            meter,
            quantity,
            ADJUST,
            f"{ADJUST_PREFIX}{uuid4().hex}",
            res.period[0],
            source=ADMIN_SOURCE,
            actor=actor,
            reason=reason.strip(),
        )
        outcome = await run_write(self._factory, None, self._counter(event, res, None))
        return outcome.used
