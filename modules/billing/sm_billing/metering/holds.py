"""Gauge holds: ``reserve`` / ``commit`` / ``release`` / ``extend`` / ``holding``.

Every call is its own short transaction, finished with ``finalize_session``
(``metering.tx``): a hold must be visible to concurrent requests before the
caller's work finishes, and it outlives the request (a job runs in a worker).
There is no ``db=`` mode.

``reserve`` is the counter's shape on ``billing_usage_gauge``: claim the key
on ``billing_usage_hold`` first (the write that takes SQLite's lock), then the
conditional upsert. Every way capacity comes back — ``release``, expiry by
the sweeper or by a late ``commit``/``extend`` — goes through
``hold_sql.settle``'s guarded transition, so it is returned exactly once.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import select, update

from sm_billing.contracts.metering import (
    LIVE_HOLD_STATUSES,
    Exceeded,
    Hold,
    HoldExpired,
    HoldNotFound,
    HoldStatus,
    IdempotencyConflict,
    MeterKind,
    QuotaExceededError,
)
from sm_billing.metering import hold_sql
from sm_billing.metering.core import MeteringCore
from sm_billing.metering.periods import as_utc
from sm_billing.metering.tx import Counted, run_write
from sm_billing.metering.validate import check_call, check_hold_id, check_text, check_ttl
from sm_billing.models import UsageGauge, UsageHold

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_REPLAY = "replay"
_GAUGE = MeterKind.GAUGE


@dataclass(frozen=True)
class _Kept(Counted):
    """A write to keep, carrying the row it returned."""

    row: Any = None


def _hold(row: Any, *, replayed: bool = False) -> Hold:
    return Hold(
        id=row.id,
        tenant_id=row.tenant_id,
        meter=row.meter,
        quantity=int(row.quantity),
        status=row.status,
        expires_at=None if row.expires_at is None else as_utc(row.expires_at),
        replayed=replayed,
    )


class HoldsMixin(MeteringCore):
    """The gauge half of ``UsageService``."""

    # ── reads ────────────────────────────────────────────────────────
    async def _find_hold(self, hold_id: str) -> Any:
        async with self._factory() as session:
            stmt = select(*hold_sql.HOLD_COLUMNS).where(UsageHold.id == hold_id)
            return (await session.execute(stmt)).one_or_none()

    async def in_use(self, tenant_id: str, meter: str) -> int:
        async with self._factory() as session:
            stmt = select(UsageGauge.in_use).where(
                UsageGauge.tenant_id == tenant_id, UsageGauge.meter == meter
            )
            return int((await session.execute(stmt)).scalar_one_or_none() or 0)

    # ── reserve ──────────────────────────────────────────────────────
    async def reserve(
        self,
        tenant_id: str,
        meter: str,
        qty: int,
        idempotency_key: str,
        *,
        source: str,
        ttl: int | None = None,
    ) -> Hold | Exceeded:
        check_call(tenant_id, meter, qty, idempotency_key, source)
        definition = self._require(meter, _GAUGE)
        seconds = check_ttl(ttl if ttl is not None else self._default_ttl(definition))
        limit = (await self._resolve(tenant_id, meter, None)).limit
        now = self._clock()
        values = {
            "id": uuid4().hex,
            "tenant_id": tenant_id,
            "meter": meter,
            "quantity": qty,
            "status": HoldStatus.HELD.value,
            "idempotency_key": idempotency_key,
            "expires_at": now + timedelta(seconds=seconds),
            "created_at": now,
            "source": source,
        }

        async def apply(session: AsyncSession) -> Counted | str | None:
            dialect = session.get_bind().dialect.name
            claimed = await session.execute(hold_sql.insert_hold(dialect, **values))
            if claimed.scalar_one_or_none() is None:
                return _REPLAY
            fields = {"tenant_id": tenant_id, "meter": meter, "qty": qty, "now": now}
            if limit is not None and qty > limit:
                stmt = hold_sql.raise_within_limit(**fields, limit=limit)
            else:
                stmt = hold_sql.upsert_gauge(dialect, **fields, limit=limit)
            level = (await session.execute(stmt)).scalar_one_or_none()
            return None if level is None else Counted(int(level))

        outcome = await run_write(self._factory, None, apply)
        if isinstance(outcome, Counted):
            return Hold(
                values["id"], tenant_id, meter, qty, HoldStatus.HELD.value, values["expires_at"]
            )
        if outcome == _REPLAY:
            replayed = await self._replay_hold(values)
            if replayed is not None:
                return replayed
        level = await self.in_use(tenant_id, meter)
        logger.info(
            "billing: hold refused tenant=%s meter=%s in_use=%s qty=%s limit=%s",
            tenant_id,
            meter,
            level,
            qty,
            limit,
        )
        return Exceeded(level, limit or 0, qty, None)

    async def _replay_hold(self, call: dict) -> Hold | None:
        """The hold first made under ``call``'s key, if the call is the same one."""
        async with self._factory() as session:
            stmt = select(*hold_sql.HOLD_COLUMNS, UsageHold.source).where(
                UsageHold.tenant_id == call["tenant_id"],
                UsageHold.meter == call["meter"],
                UsageHold.idempotency_key == call["idempotency_key"],
            )
            row = (await session.execute(stmt)).one_or_none()
        if row is None:
            return None  # purged between the claim and this read
        if (int(row.quantity), row.source) != (call["quantity"], call["source"]):
            raise IdempotencyConflict(call["idempotency_key"])
        return _hold(row, replayed=True)

    # ── settling ─────────────────────────────────────────────────────
    async def _settle(self, hold_id: str, to: HoldStatus, from_, *, due: bool) -> Any:
        """The guarded transition plus the gauge decrement; the row if this call won."""
        now = self._clock()

        async def apply(session: AsyncSession) -> _Kept | None:
            stmt = hold_sql.settle(hold_id, to=to.value, from_=from_, now=now, due=due)
            row = (await session.execute(stmt)).one_or_none()
            if row is None:
                return None
            await session.execute(
                hold_sql.lower_gauge(
                    tenant_id=row.tenant_id, meter=row.meter, qty=int(row.quantity), now=now
                )
            )
            return _Kept(0, row)

        outcome = await run_write(self._factory, None, apply)
        return outcome.row if isinstance(outcome, _Kept) else None

    async def expire(self, hold_id: str) -> bool:
        """Expire a ``held`` hold past its ``expires_at``; ``True`` if this call did."""
        due = (HoldStatus.HELD.value,)
        return await self._settle(hold_id, HoldStatus.EXPIRED, due, due=True) is not None

    async def release(self, hold_id: str) -> bool:
        check_hold_id(hold_id)
        live = sorted(LIVE_HOLD_STATUSES)
        if await self._settle(hold_id, HoldStatus.RELEASED, live, due=False) is not None:
            return True
        if await self._find_hold(hold_id) is None:
            raise HoldNotFound(hold_id)
        return False

    async def _held_update(self, hold_id: str, expires_at: datetime | None, status: str) -> Any:
        """Move a ``held``, not yet lapsed hold to ``status``/``expires_at``."""
        now = self._clock()

        async def apply(session: AsyncSession) -> _Kept | None:
            stmt = (
                update(UsageHold)
                .where(
                    UsageHold.id == hold_id,
                    UsageHold.status == HoldStatus.HELD.value,
                    UsageHold.expires_at > now,
                )
                .values(status=status, expires_at=expires_at)
                .returning(*hold_sql.HOLD_COLUMNS)
            )
            row = (await session.execute(stmt)).one_or_none()
            return None if row is None else _Kept(0, row)

        outcome = await run_write(self._factory, None, apply)
        if isinstance(outcome, _Kept):
            return _hold(outcome.row)
        row = await self._find_hold(hold_id)
        if row is None:
            raise HoldNotFound(hold_id)
        if row.status == HoldStatus.COMMITTED:
            return _hold(row)  # nothing to extend, and committing again is a no-op
        if row.status == HoldStatus.HELD:  # lapsed, the sweeper has not run yet
            await self.expire(hold_id)
            raise HoldExpired(hold_id, HoldStatus.EXPIRED.value)
        raise HoldExpired(hold_id, row.status)

    async def commit(self, hold_id: str) -> Hold:
        check_hold_id(hold_id)
        return await self._held_update(hold_id, None, HoldStatus.COMMITTED.value)

    async def extend(self, hold_id: str, ttl: int) -> Hold:
        check_hold_id(hold_id)
        expires_at = self._clock() + timedelta(seconds=check_ttl(ttl))
        return await self._held_update(hold_id, expires_at, HoldStatus.HELD.value)

    @asynccontextmanager
    async def holding(
        self,
        tenant_id: str,
        meter: str,
        qty: int,
        idempotency_key: str,
        *,
        source: str,
        ttl: int | None = None,
    ) -> AsyncIterator[Hold]:
        """Reserve for the block and release after it, raised or not.

        A replayed key yields the original hold but leaves releasing it to the
        call that made it; one already settled raises ``HoldExpired``.
        """
        outcome = await self.reserve(tenant_id, meter, qty, idempotency_key, source=source, ttl=ttl)
        if isinstance(outcome, Exceeded):
            raise QuotaExceededError(meter, outcome)
        if not outcome.ok:
            raise HoldExpired(outcome.id, outcome.status)
        try:
            yield outcome
        finally:
            if not outcome.replayed:
                # Shielded: a cancelled job must still give its slot back.
                await asyncio.shield(self.release(outcome.id))

    # ── repair ───────────────────────────────────────────────────────
    async def recount(self, tenant_id: str, meter: str) -> int:
        """Rebuild the level from the live (held and committed) holds; returns it.

        The admin repair for drift (a bug that bypassed the service). Lapsed
        holds the sweeper has not expired yet still count, as they do in the
        gauge until it does.
        """
        check_text("tenant_id", tenant_id, 32)
        self._require(meter, _GAUGE)
        now = self._clock()
        fields = {"tenant_id": tenant_id, "meter": meter, "now": now}

        async def apply(session: AsyncSession) -> Counted:
            dialect = session.get_bind().dialect.name
            await session.execute(hold_sql.touch_gauge(dialect, **fields))
            level = (await session.execute(hold_sql.recount(**fields))).scalar_one()
            return Counted(int(level))

        outcome = await run_write(self._factory, None, apply)
        return outcome.used
