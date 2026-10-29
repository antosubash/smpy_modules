"""``swap``: replace a gauge hold with a committed one in one transaction.

A consumer that keeps one hold per resource (``images`` holds each image's
stored bytes) must move that hold when the resource's size changes. Done as
two calls - reserve and commit the new hold, then release the old - the
consumer has to choose an order, and either one leaves a window: release
first and the resource is counted by nothing until the new hold fits; reserve
first and it is counted twice, which near the limit refuses a resize that
would fit. ``swap`` does it in one transaction:

1. claim the key with a new hold, ``committed`` (no expiry) from the start;
2. release the old hold - only one of the tenant's own, on the same meter,
   still live (a ``held`` hold past its expiry still counts in the gauge, so
   it is freed too); an old hold already settled, or unknown, frees nothing
   and the call is a plain reserve and commit;
3. raise the level by the new quantity within the limit, after the old one
   was taken off: the check is on the net delta. A delta of zero or less is
   admitted even over the limit (a plan lowered under the tenant must not stop
   a resource from shrinking).

A refusal rolls everything back, so the old hold still counts - and then the
key's outcome is made durable: a ``refused`` row under the key (counted by
nothing). A later call with the same key - a retry, or a delayed duplicate of
the first call - returns the same refusal and never mutates; and a replay must
be the same call (quantity, source *and* old hold), else
``IdempotencyConflict``. Two calls with one key: the first durable row wins
and both answer with it. On Postgres two swaps of one old hold serialise on
its row: the second finds it settled and has to fit its whole quantity.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import select, update

from sm_billing.contracts.metering import (
    LIVE_HOLD_STATUSES,
    Exceeded,
    Hold,
    HoldNotFound,
    HoldStatus,
    IdempotencyConflict,
    MeterKind,
)
from sm_billing.metering import hold_sql
from sm_billing.metering.holds import HoldsMixin, _hold
from sm_billing.metering.tx import Counted, run_write
from sm_billing.metering.validate import check_call, check_hold_id
from sm_billing.models import UsageHold

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_REPLAY, _FOREIGN = "replay", "foreign"


def _release_old(old: str, tenant_id: str, meter: str, now: datetime) -> Any:
    hold = hold_sql.HOLD
    return (
        update(hold)
        .where(
            hold.c.id == old,
            hold.c.tenant_id == tenant_id,
            hold.c.meter == meter,
            hold.c.status.in_(sorted(LIVE_HOLD_STATUSES)),
        )
        .values(status=HoldStatus.RELEASED.value, settled_at=now)
        .returning(hold.c.quantity)
    )


class SwapMixin(HoldsMixin):
    """``swap`` on top of the gauge holds."""

    async def swap(
        self,
        tenant_id: str,
        meter: str,
        old_hold_id: str | None,
        quantity: int,
        idempotency_key: str,
        *,
        source: str,
    ) -> Hold | Exceeded:
        check_call(tenant_id, meter, quantity, idempotency_key, source)
        if old_hold_id is not None:
            check_hold_id(old_hold_id)
        self._require(meter, MeterKind.GAUGE)
        limit = (await self._resolve(tenant_id, meter, None)).limit
        now = self._clock()
        values = {
            "id": uuid4().hex,
            "tenant_id": tenant_id,
            "meter": meter,
            "quantity": quantity,
            "status": HoldStatus.COMMITTED.value,
            "idempotency_key": idempotency_key,
            "expires_at": None,
            "created_at": now,
            "source": source,
            "replaces_hold_id": old_hold_id,
        }
        freed = 0

        async def apply(session: AsyncSession) -> Counted | str | None:
            nonlocal freed
            dialect = session.get_bind().dialect.name
            claimed = await session.execute(hold_sql.insert_hold(dialect, **values))
            if claimed.scalar_one_or_none() is None:
                return _REPLAY
            freed = 0
            if old_hold_id is not None:
                row = (
                    await session.execute(_release_old(old_hold_id, tenant_id, meter, now))
                ).first()
                if row is not None:
                    freed = int(row.quantity)
                    await session.execute(
                        hold_sql.lower_gauge(tenant_id=tenant_id, meter=meter, qty=freed, now=now)
                    )
                elif await self._foreign(session, old_hold_id, tenant_id, meter):
                    return _FOREIGN
            fields = {"tenant_id": tenant_id, "meter": meter, "qty": quantity, "now": now}
            bound = None if quantity <= freed else limit  # a shrink is never refused
            if bound is not None and quantity > bound:
                stmt = hold_sql.raise_within_limit(**fields, limit=bound)
            else:
                stmt = hold_sql.upsert_gauge(dialect, **fields, limit=bound)
            level = (await session.execute(stmt)).scalar_one_or_none()
            return None if level is None else Counted(int(level))

        outcome = await run_write(self._factory, None, apply)
        if isinstance(outcome, Counted):
            return Hold(values["id"], tenant_id, meter, quantity, values["status"], None)
        if outcome == _FOREIGN:
            raise HoldNotFound(old_hold_id or "")
        if outcome != _REPLAY:
            outcome = await run_write(self._factory, None, self._refusal(values, now))
            if isinstance(outcome, Counted):  # the key's outcome is this refusal
                level = await self.in_use(tenant_id, meter)
                return Exceeded(level, limit or 0, quantity - freed, None)
        return await self._replay_swap(values, limit)

    @staticmethod
    def _refusal(values: dict, now: datetime) -> Any:
        """Record the refusal under the key, unless another call's row has it."""
        row = {**values, "id": uuid4().hex, "status": HoldStatus.REFUSED.value, "settled_at": now}

        async def apply(session: AsyncSession) -> Counted | None:
            dialect = session.get_bind().dialect.name
            claimed = await session.execute(hold_sql.insert_hold(dialect, **row))
            return None if claimed.scalar_one_or_none() is None else Counted(0)

        return apply

    async def _replay_swap(self, call: dict, limit: int | None) -> Hold | Exceeded:
        """The outcome first recorded under ``call``'s key, if it is the same call."""
        async with self._factory() as session:
            stmt = select(
                *hold_sql.HOLD_COLUMNS, UsageHold.source, UsageHold.replaces_hold_id
            ).where(
                UsageHold.tenant_id == call["tenant_id"],
                UsageHold.meter == call["meter"],
                UsageHold.idempotency_key == call["idempotency_key"],
            )
            row = (await session.execute(stmt)).one_or_none()
        if row is None:  # purged by retention since: nothing to replay
            raise IdempotencyConflict(call["idempotency_key"])
        same = (int(row.quantity), row.source, row.replaces_hold_id)
        if same != (call["quantity"], call["source"], call["replaces_hold_id"]):
            raise IdempotencyConflict(call["idempotency_key"])
        if row.status == HoldStatus.REFUSED.value:
            level = await self.in_use(call["tenant_id"], call["meter"])
            return Exceeded(level, limit or 0, call["quantity"], None)
        return _hold(row, replayed=True)

    @staticmethod
    async def _foreign(session: AsyncSession, hold_id: str, tenant_id: str, meter: str) -> bool:
        """``hold_id`` exists but belongs to another tenant or meter."""
        stmt = select(UsageHold.tenant_id, UsageHold.meter).where(UsageHold.id == hold_id)
        row = (await session.execute(stmt)).first()
        return row is not None and (row.tenant_id, row.meter) != (tenant_id, meter)
